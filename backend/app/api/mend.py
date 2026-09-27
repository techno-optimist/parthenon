"""
The mend: records already written in the wrong language, put right in place
(see services/language_mend.py).

GET /api/parthenon/mend/scan?scope=all[&lang=en]
    What is written in the wrong language, record by record, and what the mend
    would do with it. No model, no writes.
POST /api/parthenon/mend  {"scope": "all", "apply": false, "lang": null}
    A dry run unless apply is true: the lines are translated (and kept, so the
    run that applies them makes no further calls) and nothing is written.
    With apply, every file is copied under the upload folder's _mend_backups
    first. Answers when it is done: it runs from the owner's machine or from
    inside the container, never through the site's edge.

scope is 'all', 'report:<id>', 'simulation:<id>', 'project:<id>' (the whole
gathering) or 'graph:<graph_id>'. lang ('en' or 'zh', optional) decides the
language of the records the scope names when their language is only a guess:
a record whose question reads English but whose record reads Chinese is left
as uncertain until a request names it with lang 'en'. A record's own scope
only settles a guess lang agrees with; 'project:<id>' with lang decides the
whole gathering, and applying keeps lang on its project, so every reader of
the gathering takes that language from then on. On the public steps
both routes are the keepers' alone (X-Parthenon-Admin, public/guard.py); on
the owner's own machine they are open like the rest of the app.
"""

import logging

from flask import Blueprint, jsonify, request

from ..services import language_mend

logger = logging.getLogger('mirofish.api.mend')

mend_bp = Blueprint('mend', __name__)

_BAD_REQUEST = (language_mend.ScopeError, language_mend.LanguageError)


def _refused(message, status):
    return jsonify({'success': False, 'error': message}), status


@mend_bp.route('/scan', methods=['GET'])
def scan_records():
    try:
        summary = language_mend.scan(
            request.args.get('scope') or language_mend.SCOPE_ALL, lang=request.args.get('lang'),
        )
    except _BAD_REQUEST as error:
        return _refused(str(error), 400)
    return jsonify({'success': True, 'data': summary})


@mend_bp.route('', methods=['POST'], strict_slashes=False)
def mend_records():
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        return _refused('Send {"scope": "all", "apply": false}.', 400)
    apply = body.get('apply', False)
    if not isinstance(apply, bool):
        return _refused('apply is true or false.', 400)
    try:
        summary = language_mend.mend(
            body.get('scope') or language_mend.SCOPE_ALL, apply=apply, lang=body.get('lang'),
        )
    except _BAD_REQUEST as error:
        return _refused(str(error), 400)
    except language_mend.MendBusy as error:
        return _refused(str(error), 409)
    except Exception as error:  # noqa: BLE001 - what it wrote before stopping has its copies
        logger.error('The mend stopped: %s', type(error).__name__, exc_info=error)
        return _refused(f'The mend stopped ({type(error).__name__}); the files it wrote have their copies.', 500)
    return jsonify({'success': True, 'data': summary})
