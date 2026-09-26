"""Film the Chronicle: screenplay, Grok Imagine/voice bridge calls, ffmpeg cut and API.

No real xAI calls: the bridge is an httpx.MockTransport and the screenwriter a fake.
"""

import base64
import copy
import io
import json
import os
import subprocess
import threading
import time

import httpx
import pytest
from PIL import Image

from app import create_app
from app.config import Config
from app.services import chronicle_film as film
from app.services.report_agent import (
    Report,
    ReportManager,
    ReportOutline,
    ReportSection,
    ReportStatus,
)


FFMPEG = film.find_tool('ffmpeg')
FFPROBE = film.find_tool('ffprobe')
needs_ffmpeg = pytest.mark.skipif(not (FFMPEG and FFPROBE), reason='ffmpeg is not installed')

BRIDGE_URL = 'http://127.0.0.1:5055/v1'
VIDEO_URL = 'https://vidgen.x.ai/test/clip.mp4'
REPORT_ID = 'report_0123456789ab'
APPEARANCE = 'a grey-bearded stonemason in his sixties, dust-streaked blue tunic, leather apron'
IMAGINE_MESSAGE = 'Grok Imagine needs the Grok subscription upstream.'

SCREENPLAY = {
    'title': 'The Marble Question',
    'logline': 'A city argues over whether to rebuild its temple.',
    'style_bible': {
        'look': 'Kodak 250D, low golden light',
        'palette': 'Marble white, ochre, deep Aegean blue',
        'camera': 'Slow dolly moves on a 40mm anamorphic lens',
        'era': 'Athens, 432 BC',
    },
    'cast': [
        {'name': 'Ictinus', 'appearance': APPEARANCE},
        {'name': 'Nobody'},
    ],
    'shots': [
        {
            'narration': 'Athens, at dawn. [pause] A city asks what its temple is worth.',
            'image_prompt': 'Wide establishing shot of the Acropolis at dawn, scaffolding on the temple.',
            'motion_prompt': 'MOTION-1 slow crane up over the city.',
            'duration': 7,
        },
        {
            'narration': 'Ictinus argues that <soft>marble outlives men</soft>.',
            'image_prompt': 'SHOT-TWO Ictinus speaks in the agora, hand raised.',
            'motion_prompt': 'MOTION-2 slow push-in on his face.',
            'duration': 6,
        },
        {
            'narration': 'The farmers answer: bread first.',
            'image_prompt': 'Farmers gather at the edge of the assembly, arms folded.',
            'motion_prompt': 'MOTION-3 gentle handheld drift.',
            'duration': 6,
        },
        {
            'narration': 'By dusk, the city votes to build.',
            'image_prompt': 'Citizens drop pebbles into urns at dusk.',
            'motion_prompt': 'MOTION-4 slow pull back.',
            'duration': 8,
        },
    ],
}


# ── fixtures and fakes ──

def _run_ffmpeg(*args):
    subprocess.run([FFMPEG, '-hide_banner', '-loglevel', 'error', '-y', *args],
                   check=True, capture_output=True)


@pytest.fixture(scope='session')
def media(tmp_path_factory):
    folder = tmp_path_factory.mktemp('film-media')
    buffer = io.BytesIO()
    Image.new('RGB', (96, 54), (180, 150, 90)).save(buffer, 'JPEG')
    result = {'jpeg': buffer.getvalue(), 'mp4': None, 'mp3': None}
    if FFMPEG and FFPROBE:
        mp4 = folder / 'clip.mp4'
        mp3 = folder / 'voice.mp3'
        _run_ffmpeg('-f', 'lavfi', '-i', 'testsrc=size=184x100:rate=24:duration=1',
                    '-f', 'lavfi', '-i', 'sine=frequency=440:duration=1',
                    '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest', str(mp4))
        _run_ffmpeg('-f', 'lavfi', '-i', 'sine=frequency=220:duration=0.6',
                    '-c:a', 'libmp3lame', '-b:a', '64k', str(mp3))
        result['mp4'] = mp4.read_bytes()
        result['mp3'] = mp3.read_bytes()
    return result


class FakeBridge:
    """The LLM bridge's Grok Imagine and voice routes, plus the video CDN."""

    def __init__(self, media, *, image_error=None, video_outcome=None,
                 reject_resolution=False, pending_polls=1):
        self.media = media
        self.image_error = image_error or (lambda prompt: None)
        self.video_outcome = video_outcome or (lambda prompt: 'done')
        self.reject_resolution = reject_resolution
        self.pending_polls = pending_polls
        self.requests = []
        self.videos = {}
        self.polls = {}
        self.lock = threading.Lock()

    def calls(self, path):
        with self.lock:
            return [body for method, seen, body in self.requests if seen == path]

    def __call__(self, request):
        if request.url.host == 'vidgen.x.ai':
            return httpx.Response(200, content=self.media['mp4'], headers={'content-type': 'video/mp4'})
        path = request.url.path
        body = json.loads(request.content) if request.content else None
        with self.lock:
            self.requests.append((request.method, path, body))
        if path == '/v1/images/generations':
            error = self.image_error(body['prompt'])
            if error:
                return httpx.Response(error[0], json=error[1])
            encoded = base64.b64encode(self.media['jpeg']).decode('ascii')
            return httpx.Response(200, json={'data': [{'b64_json': encoded, 'mime_type': 'image/jpeg'}]})
        if path == '/v1/videos/generations':
            if self.reject_resolution and 'resolution' in body:
                return httpx.Response(400, json={'error': {'message': 'unknown field resolution'}})
            with self.lock:
                request_id = f'req-{len(self.videos) + 1}'
                self.videos[request_id] = body['prompt']
            return httpx.Response(200, json={'request_id': request_id})
        if path.startswith('/v1/videos/'):
            request_id = path.rsplit('/', 1)[1]
            with self.lock:
                self.polls[request_id] = self.polls.get(request_id, 0) + 1
                polls = self.polls[request_id]
                prompt = self.videos[request_id]
            if polls <= self.pending_polls:
                return httpx.Response(202, json={'status': 'pending', 'progress': 40})
            outcome = self.video_outcome(prompt)
            if outcome == 'done':
                return httpx.Response(200, json={
                    'status': 'done',
                    'video': {'url': VIDEO_URL, 'duration': 1, 'respect_moderation': True},
                    'model': 'grok-imagine-video-1.5',
                    'progress': 100,
                })
            return httpx.Response(200, json={'status': outcome})
        if path == '/v1/tts':
            return httpx.Response(200, content=self.media['mp3'], headers={'content-type': 'audio/mpeg'})
        return httpx.Response(404, text='<h1>Not Found</h1>', headers={'content-type': 'text/html'})


class FakeLLM:
    def __init__(self, screenplay=SCREENPLAY, gate=None):
        self.screenplay = screenplay
        self.gate = gate
        self.calls = []

    def chat_json(self, messages, **kwargs):
        self.calls.append(messages)
        if self.gate is not None:
            assert self.gate.wait(30)
        return copy.deepcopy(self.screenplay)


@pytest.fixture
def reports_dir(tmp_path, monkeypatch):
    folder = tmp_path / 'reports'
    monkeypatch.setattr(ReportManager, 'REPORTS_DIR', str(folder))
    yield folder
    with film._jobs_lock:
        film._active_jobs.clear()


def _save_report(report_id=REPORT_ID, status=ReportStatus.COMPLETED):
    report = Report(
        report_id=report_id,
        simulation_id='sim_test',
        graph_id='graph_test',
        simulation_requirement='Should Athens rebuild its temple with public money?',
        status=status,
        outline=ReportOutline(
            title='The Marble Question',
            summary='The assembly split, then voted to build.',
            sections=[ReportSection(title='The vote', content='The city voted to build.')],
        ),
        markdown_content='# The Marble Question\n\nIctinus argued for marble; the farmers for bread.',
        created_at='2026-09-25T10:00:00',
    )
    ReportManager.save_report(report)
    return report


def _bridge(fake):
    return film.FilmBridge(BRIDGE_URL, transport=httpx.MockTransport(fake))


def _film(report, fake, llm=None):
    maker = film.ChronicleFilmMaker(
        report, voice='eve', locale='en', bridge=_bridge(fake), llm=llm or FakeLLM(),
        ffmpeg=FFMPEG, ffprobe=FFPROBE,
    )
    maker.poll_seconds = 0
    maker.begin()
    maker.run()
    return film.read_manifest(report.report_id)


def _folder(report_id=REPORT_ID):
    return film.film_folder(report_id)


def _probe(path):
    result = subprocess.run(
        [FFPROBE, '-v', 'error', '-print_format', 'json', '-show_format', '-show_streams', path],
        check=True, capture_output=True,
    )
    return json.loads(result.stdout)


def _cue_starts(vtt):
    return [line.split(' --> ')[0] for line in vtt.splitlines() if ' --> ' in line]


# ── settings ──

def test_bridge_url_prefers_env_then_loopback_llm_base(monkeypatch):
    monkeypatch.setenv('PARTHENON_BRIDGE_URL', 'http://127.0.0.1:6000/')
    assert film.bridge_base_url() == 'http://127.0.0.1:6000/v1'
    monkeypatch.delenv('PARTHENON_BRIDGE_URL')
    monkeypatch.setattr(Config, 'LLM_BASE_URL', 'http://localhost:5056/v1')
    assert film.bridge_base_url() == 'http://localhost:5056/v1'
    monkeypatch.setattr(Config, 'LLM_BASE_URL', 'https://api.openai.com/v1')
    assert film.bridge_base_url() == 'http://127.0.0.1:5055/v1'


def test_models_come_from_env(monkeypatch):
    monkeypatch.delenv('FILM_IMAGE_MODEL', raising=False)
    monkeypatch.setenv('FILM_VIDEO_MODEL', 'grok-imagine-video-2.0')
    assert film.film_image_model() == 'grok-imagine-image-2.0'
    assert film.film_video_model() == 'grok-imagine-video-2.0'


@pytest.mark.parametrize('value, expected', [(None, 'rex'), ('', 'rex'), (' EVE ', 'eve'), ('ara', 'ara')])
def test_voice_normalisation(value, expected):
    assert film.normalise_voice(value) == expected


@pytest.mark.parametrize('value', ['bob', 3, ['rex']])
def test_bad_voice_is_rejected(value):
    with pytest.raises(film.FilmValidationError):
        film.normalise_voice(value)


@pytest.mark.parametrize('value', [3, 9, True, '5', 5.0])
def test_bad_shot_count_is_rejected(value):
    with pytest.raises(film.FilmValidationError):
        film.normalise_shot_count(value)


# ── screenplay ──

def test_screenplay_normalisation_clamps_and_fills():
    long_narration = ' '.join(f'word{n}' for n in range(60))
    shots = [
        {'narration': 'Short line.', 'duration': 2, 'image_prompt': 'A wide shot.'},
        {'narration': 'Another short line.', 'duration': 30},
        {'narration': 'Third line.', 'duration': '8s', 'motion_prompt': '  slow   push-in '},
        {'narration': f'<soft>{long_narration}', 'duration': 'soon'},
        {'narration': '<shout>Loud</shout> [music] words [PAUSE] here </soft>'},
        {'narration': ''},
        {'narration': '[pause]'},
        'not a shot',
    ] + [{'narration': f'Extra shot {n}.'} for n in range(10)]
    screenplay = film.normalise_screenplay({
        'title': '  The   Marble\nQuestion ',
        'style_bible': {'look': 'Kodak 250D', 'palette': 42},
        'cast': [
            {'name': 'Ictinus', 'appearance': APPEARANCE},
            {'name': 'ictinus', 'appearance': 'a duplicate'},
            {'name': 'Nobody'},
            'junk',
        ],
        'shots': shots,
    })

    assert screenplay['title'] == 'The Marble Question'
    assert screenplay['logline'] == ''
    assert screenplay['style_bible']['look'] == 'Kodak 250D'
    assert screenplay['style_bible']['palette'] == film.DEFAULT_STYLE['palette']
    assert screenplay['style_bible']['camera'] == film.DEFAULT_STYLE['camera']
    assert screenplay['cast'] == [{'name': 'Ictinus', 'appearance': APPEARANCE}]

    result = screenplay['shots']
    assert len(result) == film.MAX_SHOTS
    assert [shot['duration'] for shot in result[:3]] == [6, film.MAX_SHOT_SECONDS, 8]
    assert all(film.MIN_SHOT_SECONDS <= shot['duration'] <= film.MAX_SHOT_SECONDS for shot in result)
    assert result[0]['image_prompt'] == 'A wide shot.'
    assert result[1]['image_prompt'] == 'Another short line.'  # filled from the narration
    assert result[1]['motion_prompt'] == film.DEFAULT_MOTION
    assert result[2]['motion_prompt'] == 'slow push-in'

    capped = result[3]
    assert capped['narration'].startswith('<soft>') and capped['narration'].endswith('</soft>')
    assert capped['caption'].endswith('…')
    assert len(capped['caption'].split()) <= film.MAX_NARRATION_WORDS
    assert capped['duration'] == 10  # 22 words need about 9.6 s, more than the requested default

    tagged = result[4]
    assert tagged['narration'] == 'Loud words [pause] here'
    assert tagged['caption'] == 'Loud words here'


def test_cjk_narration_is_capped_by_characters():
    narration = film.clean_narration('雅典' * 60 + '。')
    # MAX_NARRATION_CJK_CHARS characters fill the whole word budget.
    assert narration.endswith('…') and len(narration) == film.MAX_NARRATION_CJK_CHARS + 1
    assert film.spoken_seconds('雅典人投票。') == pytest.approx(5 / film.CJK_CHARS_PER_SECOND)
    assert film.tts_language('zh') == 'zh' and film.tts_language('ja') == 'auto'


def test_screenplay_honours_requested_count_and_unwraps():
    wrapped = {'screenplay': {'title': 'T', 'shots': [{'narration': f'Line {n}.'} for n in range(7)]}}
    screenplay = film.normalise_screenplay(wrapped, shot_count=4)
    assert len(screenplay['shots']) == 4


def test_screenplay_without_usable_shots_fails():
    with pytest.raises(film.FilmError):
        film.normalise_screenplay({'title': 'T', 'shots': [{'narration': '  '}]})
    with pytest.raises(film.FilmError):
        film.normalise_screenplay(['not', 'an', 'object'])
    fallback = film.normalise_screenplay({'shots': [{'narration': 'One.'}]}, fallback_title='Chronicle')
    assert fallback['title'] == 'Chronicle'


def test_screenplay_prompt_carries_chronicle_and_language():
    report = Report(
        report_id=REPORT_ID, simulation_id='sim', graph_id='g',
        simulation_requirement='Should the city rebuild?', status=ReportStatus.COMPLETED,
        markdown_content='# Chronicle\n\nThe vote was close.',
    )
    messages = film.build_screenplay_messages(
        report, shot_count=6, language_instruction='Please respond in English.'
    )
    assert messages[0]['role'] == 'system' and '50 to 75 seconds' in messages[0]['content']
    user = messages[1]['content']
    assert 'Should the city rebuild?' in user and 'The vote was close.' in user
    assert 'exactly 6 shots' in user and 'Please respond in English.' in user


def test_image_prompt_repeats_cast_appearance_and_style():
    screenplay = film.normalise_screenplay(copy.deepcopy(SCREENPLAY))
    second = film.compose_image_prompt(screenplay['shots'][1], screenplay)
    assert APPEARANCE in second and 'Athens, 432 BC' in second and 'No text' in second
    first = film.compose_image_prompt(screenplay['shots'][0], screenplay)
    assert APPEARANCE not in first  # Ictinus is not in the establishing shot
    assert len(first) <= film.MAX_IMAGE_PROMPT_CHARS


def test_captions_strip_voice_tags_and_split_long_lines():
    vtt = film.build_captions([
        (3.2, 9.0, 'The city gathers at dawn. <soft>Bread & marble</soft> [pause] divide it.'),
        (12.0, 20.0, ' '.join(['word'] * 30) + ', ' + ' '.join(['more'] * 10) + '.'),
    ])
    assert vtt.startswith('WEBVTT\n')
    assert '[pause]' not in vtt and '<soft>' not in vtt
    assert 'Bread &amp; marble divide it.' in vtt
    starts = _cue_starts(vtt)
    assert starts[0] == '00:00:03.200'
    assert len(starts) == 4 and starts[2] == '00:00:12.000'
    assert '00:00:20.000' in vtt


# ── bridge ──

def test_video_resolution_is_dropped_after_a_400(media):
    fake = FakeBridge(media, reject_resolution=True)
    bridge = _bridge(fake)
    assert bridge.start_video('move', b'jpeg', 6) == 'req-1'
    assert bridge.start_video('move', b'jpeg', 7) == 'req-2'
    sent = fake.calls('/v1/videos/generations')
    assert ['resolution' in body for body in sent] == [True, False, False]
    assert sent[1]['image']['url'] == 'data:image/jpeg;base64,' + base64.b64encode(b'jpeg').decode()
    assert sent[1]['model'] == 'grok-imagine-video-1.5' and sent[2]['duration'] == 7


def test_video_poll_waits_for_done(media):
    fake = FakeBridge(media, pending_polls=2)
    bridge = _bridge(fake)
    sleeps, progress = [], []
    url = bridge.wait_for_video(
        bridge.start_video('move', b'jpeg', 6), poll_seconds=5,
        sleep=sleeps.append, on_progress=progress.append,
    )
    assert url == VIDEO_URL
    assert sleeps == [5, 5] and progress == [0.4, 0.4]


def test_video_poll_reports_failure_and_timeout(media):
    bridge = _bridge(FakeBridge(media, video_outcome=lambda prompt: 'expired', pending_polls=0))
    with pytest.raises(film.BridgeError) as failed:
        bridge.wait_for_video(bridge.start_video('move', b'jpeg', 6), sleep=lambda s: None)
    assert 'expired' in str(failed.value) and not failed.value.fatal

    slow = _bridge(FakeBridge(media, pending_polls=100))
    ticks = iter(range(0, 10000, 5))
    with pytest.raises(film.BridgeError, match='too long'):
        slow.wait_for_video(
            slow.start_video('move', b'jpeg', 6), timeout_seconds=20,
            sleep=lambda s: None, clock=lambda: next(ticks),
        )


def test_bridge_errors_are_safe_and_classified(media):
    secret = 'PROMPT ECHO sk-secret'

    def handler(request):
        if request.url.path == '/v1/images/generations':
            return httpx.Response(501, json={'error': {
                'type': 'grok_bridge_error', 'code': 'imagine_unavailable', 'message': IMAGINE_MESSAGE}})
        if request.url.path == '/v1/tts':
            return httpx.Response(500, json={'error': {'message': secret, 'code': 'internal'}})
        return httpx.Response(404, text='<h1>Not Found</h1>', headers={'content-type': 'text/html'})

    bridge = film.FilmBridge(BRIDGE_URL, transport=httpx.MockTransport(handler))
    with pytest.raises(film.BridgeError) as unavailable:
        bridge.generate_image('a temple')
    assert str(unavailable.value) == IMAGINE_MESSAGE and unavailable.value.fatal

    with pytest.raises(film.BridgeError) as outdated:
        bridge.start_video('move', b'jpeg', 6)
    assert str(outdated.value) == film.BRIDGE_OUTDATED_MESSAGE and outdated.value.fatal

    with pytest.raises(film.BridgeError) as hidden:
        bridge.speak('hello', voice='rex', language='en')
    assert 'HTTP 500' in str(hidden.value) and secret not in str(hidden.value)
    assert not hidden.value.fatal


def test_tts_retries_with_auto_language(media):
    languages = []

    def handler(request):
        body = json.loads(request.content)
        languages.append(body['language'])
        if body['language'] != 'auto':
            return httpx.Response(400, json={'error': {'message': 'unsupported language'}})
        return httpx.Response(200, content=b'ID3audio', headers={'content-type': 'audio/mpeg'})

    bridge = film.FilmBridge(BRIDGE_URL, transport=httpx.MockTransport(handler))
    assert bridge.speak('你好', voice='ara', language='zh') == b'ID3audio'
    assert languages == ['zh', 'auto']


def test_video_download_refuses_unsafe_links(media, tmp_path):
    bridge = _bridge(FakeBridge(media))
    for url in ('http://example.com/clip.mp4', 'file:///etc/passwd', 'https://user@x.ai/clip.mp4'):
        with pytest.raises(film.BridgeError, match='unusable link'):
            bridge.download_video(url, str(tmp_path / 'clip.mp4'))


# ── pipeline ──

@needs_ffmpeg
def test_full_pipeline_produces_film_poster_and_captions(reports_dir, media):
    report = _save_report()
    fake = FakeBridge(media)
    manifest = _film(report, fake)

    assert manifest['status'] == 'completed', manifest['error']
    assert manifest['stage'] == 'done' and manifest['progress'] == 100
    assert manifest['title'] == 'The Marble Question' and manifest['voice'] == 'eve'
    assert [shot['status'] for shot in manifest['shots']] == ['done'] * 4
    assert [shot['thumb'] for shot in manifest['shots']] == [f'shot_{n:02d}.jpg' for n in range(1, 5)]
    assert manifest['shots'][0]['narration'] == 'Athens, at dawn. A city asks what its temple is worth.'

    folder = _folder()
    assert not os.path.exists(os.path.join(folder, film.WORK_DIR_NAME))
    info = _probe(os.path.join(folder, 'film.mp4'))
    video = next(s for s in info['streams'] if s['codec_type'] == 'video')
    audio = next(s for s in info['streams'] if s['codec_type'] == 'audio')
    assert (video['width'], video['height'], video['codec_name']) == (1280, 720, 'h264')
    assert audio['codec_name'] == 'aac'
    # Title 3.5 s + four 1.71 s shots (0.6 s narration + 1.1 s) - four 0.6 s cross-fades.
    duration = float(info['format']['duration'])
    assert 7.3 < duration < 8.6
    assert abs(manifest['duration'] - duration) < 0.05

    with Image.open(os.path.join(folder, 'poster.jpg')) as poster:
        assert poster.format == 'JPEG' and poster.size == (1280, 720)
    with open(os.path.join(folder, 'captions.vtt'), encoding='utf-8') as handle:
        vtt = handle.read()
    starts = _cue_starts(vtt)
    # One cue per sentence: the first shot's narration has two.
    assert vtt.startswith('WEBVTT') and len(starts) == 5
    assert starts[0] == '00:00:03.200'  # title 3.5 s - 0.6 s fade + 0.3 s narration delay
    assert '\nAthens, at dawn.\n' in vtt and '\nBy dusk, the city votes to build.\n' in vtt
    assert '[pause]' not in vtt and '<soft>' not in vtt
    assert os.path.exists(os.path.join(folder, film.SCREENPLAY_NAME))

    images = fake.calls('/v1/images/generations')
    assert len(images) == 4
    assert all(body['model'] == 'grok-imagine-image-2.0' and body['aspect_ratio'] == '16:9'
               and body['response_format'] == 'b64_json' and body['n'] == 1 for body in images)
    assert APPEARANCE in next(body['prompt'] for body in images if 'SHOT-TWO' in body['prompt'])
    videos = fake.calls('/v1/videos/generations')
    assert len(videos) == 4
    assert all(body['resolution'] == '720p' and body['image']['url'].startswith('data:image/jpeg;base64,')
               and 6 <= body['duration'] <= 10 for body in videos)
    speech = fake.calls('/v1/tts')
    assert len(speech) == 4
    assert all(body['voice_id'] == 'eve' and body['language'] == 'en' for body in speech)
    assert '[pause]' in speech[0]['text']


@needs_ffmpeg
def test_video_failure_falls_back_to_a_still(reports_dir, media):
    report = _save_report()
    fake = FakeBridge(
        media, video_outcome=lambda prompt: 'failed' if 'MOTION-2' in prompt else 'done'
    )
    manifest = _film(report, fake)

    assert manifest['status'] == 'completed', manifest['error']
    assert [shot['status'] for shot in manifest['shots']] == ['done', 'still', 'done', 'done']
    duration = float(_probe(os.path.join(_folder(), 'film.mp4'))['format']['duration'])
    assert duration > 11  # the still runs for its planned 6 s


@needs_ffmpeg
def test_image_failure_twice_plays_the_shot_over_a_neighbours_still(reports_dir, media):
    report = _save_report()
    fake = FakeBridge(
        media,
        image_error=lambda prompt: (500, {'error': {'message': 'boom'}}) if 'SHOT-TWO' in prompt else None,
    )
    manifest = _film(report, fake)

    assert manifest['status'] == 'completed', manifest['error']
    assert [shot['status'] for shot in manifest['shots']] == ['done', 'still', 'done', 'done']
    assert manifest['shots'][1]['thumb'] == 'shot_01.jpg'  # the nearest painted neighbour, earlier first
    assert not os.path.exists(os.path.join(_folder(), 'shot_02.jpg'))
    assert len([b for b in fake.calls('/v1/images/generations') if 'SHOT-TWO' in b['prompt']]) == 2
    assert len(fake.calls('/v1/videos/generations')) == 3
    with open(os.path.join(_folder(), 'captions.vtt'), encoding='utf-8') as handle:
        vtt = handle.read()
    # The shot's narration still tells its part of the story.
    assert len(_cue_starts(vtt)) == 5 and 'marble outlives men' in vtt


@needs_ffmpeg
def test_imagine_unavailable_fails_the_film_with_its_message(reports_dir, media):
    report = _save_report()
    fake = FakeBridge(media, image_error=lambda prompt: (501, {'error': {
        'type': 'grok_bridge_error', 'code': 'imagine_unavailable', 'message': IMAGINE_MESSAGE}}))
    manifest = _film(report, fake)

    assert manifest['status'] == 'failed'
    assert manifest['error'] == IMAGINE_MESSAGE and manifest['message'] == IMAGINE_MESSAGE
    # The narrator is recorded first (it sizes each animation); nothing is animated.
    assert len(fake.calls('/v1/tts')) == 4 and not fake.calls('/v1/videos/generations')
    folder = _folder()
    assert not os.path.exists(os.path.join(folder, 'film.mp4'))
    assert not os.path.exists(os.path.join(folder, film.WORK_DIR_NAME))
    assert not film.is_filming(REPORT_ID)


def test_screenwriter_failure_is_reported_safely(reports_dir, media):
    class BrokenLLM:
        def chat_json(self, messages, **kwargs):
            error = RuntimeError('provider body echoing the Chronicle')
            error.status_code = 503
            raise error

    report = _save_report()
    maker = film.ChronicleFilmMaker(
        report, locale='en', bridge=_bridge(FakeBridge(media)), llm=BrokenLLM(),
        ffmpeg='/bin/true', ffprobe='/bin/true',
    )
    maker.begin()
    maker.run()
    manifest = film.read_manifest(REPORT_ID)
    assert manifest['status'] == 'failed' and manifest['stage'] == 'screenplay'
    assert manifest['error'] == 'The LLM could not write the screenplay (HTTP 503).'


# ── API ──

@pytest.fixture
def client(reports_dir):
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def _use_fakes(monkeypatch, fake, llm=None):
    monkeypatch.setattr(film, '_make_bridge', lambda: _bridge(fake))
    monkeypatch.setattr(film, '_make_llm', lambda: llm or FakeLLM())
    monkeypatch.setattr(film, 'VIDEO_POLL_SECONDS', 0)
    monkeypatch.setattr(film, 'FINAL_PRESET', 'veryfast')


def _film_url(report_id=REPORT_ID, name=None):
    base = f'/api/parthenon/chronicle/{report_id}/film'
    return f'{base}/{name}' if name else base


def _wait_for_film(client, report_id=REPORT_ID, timeout=120):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        data = client.get(_film_url(report_id)).get_json()['data']
        if data['status'] != 'running' and not film.is_filming(report_id):
            return data
        time.sleep(0.1)
    raise AssertionError('the film did not finish')


@needs_ffmpeg
def test_api_films_a_chronicle_and_serves_the_files(client, media, monkeypatch):
    _save_report()
    fake = FakeBridge(media)
    _use_fakes(monkeypatch, fake)

    before = client.get(_film_url()).get_json()['data']
    assert before['status'] == 'none' and before['video_url'] is None and before['shots'] == []
    assert [voice['id'] for voice in before['voices']] == ['rex', 'eve', 'ara']

    response = client.post(_film_url(), json={'voice': 'ara', 'shots': 4},
                           headers={'Accept-Language': 'en'})
    assert response.status_code == 202
    assert response.get_json() == {'success': True, 'data': {'status': 'running', 'report_id': REPORT_ID}}

    data = _wait_for_film(client)
    assert data['status'] == 'completed', data['error']
    assert data['voice'] == 'ara' and data['report_id'] == REPORT_ID
    assert data['video_url'].startswith(f'/api/parthenon/chronicle/{REPORT_ID}/film/film.mp4?v=')
    assert data['poster_url'].startswith(_film_url(name='poster.jpg'))
    assert data['captions_url'].startswith(_film_url(name='captions.vtt'))
    assert data['shots'][0]['thumb_url'].startswith(_film_url(name='shot_01.jpg'))
    assert all(body['language'] == 'en' and body['voice_id'] == 'ara' for body in fake.calls('/v1/tts'))

    video = client.get(data['video_url'])
    assert video.status_code == 200 and video.mimetype == 'video/mp4'
    size = len(video.data)
    ranged = client.get(data['video_url'], headers={'Range': 'bytes=0-99'})
    assert ranged.status_code == 206 and len(ranged.data) == 100
    assert ranged.headers['Content-Range'] == f'bytes 0-99/{size}'
    captions = client.get(data['captions_url'])
    assert captions.mimetype == 'text/vtt' and captions.data.startswith(b'WEBVTT')
    assert client.get(data['poster_url']).mimetype == 'image/jpeg'
    assert client.get(data['shots'][0]['thumb_url']).status_code == 200


def test_api_rejects_bad_requests(client):
    _save_report()
    _save_report('report_unfinished', status=ReportStatus.GENERATING)

    assert client.post(_film_url('report_missing')).status_code == 404
    assert client.get(_film_url('report_missing')).status_code == 404
    assert client.post(_film_url('bad.id')).status_code == 404
    for body in ({'voice': 'bob'}, {'shots': 3}, {'shots': True}, {'shots': '5'}, ['rex']):
        response = client.post(_film_url(), json=body)
        assert response.status_code == 400, body
        assert response.get_json()['success'] is False
    invalid = client.post(_film_url(), data='{not json', content_type='application/json')
    assert invalid.status_code == 400
    unfinished = client.post(_film_url('report_unfinished'), json={})
    assert unfinished.status_code == 409 and 'not finished' in unfinished.get_json()['error']
    assert not film.is_filming(REPORT_ID)


def test_api_without_ffmpeg_is_unavailable(client, monkeypatch):
    _save_report()
    monkeypatch.setattr(film, 'find_tool', lambda name: None)
    response = client.post(_film_url(), json={})
    assert response.status_code == 503 and 'ffmpeg' in response.get_json()['error']


@needs_ffmpeg
def test_api_refuses_a_second_film_while_one_runs(client, media, monkeypatch):
    _save_report()
    gate = threading.Event()
    fake = FakeBridge(media, image_error=lambda prompt: (501, {'error': {
        'type': 'grok_bridge_error', 'code': 'imagine_unavailable', 'message': IMAGINE_MESSAGE}}))
    _use_fakes(monkeypatch, fake, FakeLLM(gate=gate))

    try:
        assert client.post(_film_url(), json={}).status_code == 202
        second = client.post(_film_url(), json={'voice': 'rex'})
        assert second.status_code == 409 and 'already' in second.get_json()['error']
        running = client.get(_film_url()).get_json()['data']
        assert running['status'] == 'running' and running['stage'] == 'screenplay'
        assert running['video_url'] is None
    finally:
        gate.set()
    data = _wait_for_film(client)
    assert data['status'] == 'failed' and data['error'] == IMAGINE_MESSAGE
    assert client.post(_film_url(), json={}).status_code == 202  # free again
    _wait_for_film(client)


def test_api_reports_a_film_interrupted_by_a_restart(client):
    _save_report()
    folder = _folder()
    film.write_manifest(folder, {**film.empty_manifest(), 'status': 'running', 'stage': 'frames'})
    data = client.get(_film_url()).get_json()['data']
    assert data['status'] == 'failed' and 'restarted' in data['error']
    assert film.read_manifest(REPORT_ID)['status'] == 'failed'


def test_api_serves_only_whitelisted_files(client, reports_dir):
    _save_report()
    folder = _folder()
    os.makedirs(folder, exist_ok=True)
    for name in ('film.mp4', 'shot_01.jpg', 'screenplay.json', 'shot_01.mp4', 'shot_1.jpg'):
        with open(os.path.join(folder, name), 'wb') as handle:
            handle.write(b'data')
    film.write_manifest(folder, film.empty_manifest())
    os.symlink(os.path.join(reports_dir, REPORT_ID, 'meta.json'), os.path.join(folder, 'shot_02.jpg'))

    assert client.get(_film_url(name='film.mp4')).status_code == 200
    assert client.get(_film_url(name='shot_01.jpg')).status_code == 200
    for name in ('film.json', 'screenplay.json', 'shot_01.mp4', 'shot_1.jpg', 'shot_001.jpg',
                 'FILM.MP4', 'poster.jpg', 'shot_02.jpg', '..%2Fmeta.json', '%2E%2E%2Fmeta.json',
                 '..', 'film.mp4%00.jpg'):
        response = client.get(_film_url(name=name))
        assert response.status_code == 404, name
        assert b'report_id' not in response.data
    assert client.get(f'/api/parthenon/chronicle/{REPORT_ID}/film/../meta.json').status_code == 404
    assert client.get('/api/parthenon/chronicle/..%2F..%2Fetc/film/film.mp4').status_code == 404

    assert film.film_file_path(REPORT_ID, '../meta.json') is None
    assert film.film_file_path('../' + REPORT_ID, 'film.mp4') is None
    assert film.film_file_path(REPORT_ID, 'shot_02.jpg') is None  # symlink out of the folder
    assert film.film_file_path(REPORT_ID, 'film.mp4') == os.path.realpath(os.path.join(folder, 'film.mp4'))
