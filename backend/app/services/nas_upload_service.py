"""NAS SFTP upload service — transfers media files to NAS storage."""
import os
import time
import logging

import paramiko

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_DELAY = 2


def _get_config():
    from flask import current_app
    return {
        'host': current_app.config.get('NAS_HOST', ''),
        'port': current_app.config.get('NAS_PORT', 22),
        'user': current_app.config.get('NAS_USER', ''),
        'password': current_app.config.get('NAS_PASSWORD', ''),
        'base_dir': current_app.config.get('NAS_BASE_DIR', '/Project Photo for Installation'),
        'enabled': current_app.config.get('NAS_ENABLED', False),
    }


def is_nas_enabled():
    try:
        cfg = _get_config()
        return cfg['enabled'] and bool(cfg['host'])
    except RuntimeError:
        return False


def _get_local_path(web_path, media_dir):
    relative = web_path.lstrip('/').replace('uploads/', '', 1)
    return os.path.join(media_dir, relative) if not os.path.isabs(relative) else relative


def _ensure_remote_dir(sftp, dir_path):
    try:
        sftp.mkdir(dir_path)
    except IOError:
        try:
            sftp.stat(dir_path)
        except IOError:
            parts = dir_path.split('/')
            current = ''
            for part in parts:
                if not part:
                    current = '/'
                    continue
                current = f'{current}/{part}' if current != '/' else f'/{part}'
                try:
                    sftp.stat(current)
                except IOError:
                    sftp.mkdir(current)


def _remote_photo_day_dir(base_dir, project_code, day_str):
    return f"{base_dir}/{project_code}/Photo/{day_str}"


def upload_to_nas(local_web_path, project_code, media_dir=None, *, day_str=None):
    cfg = _get_config()
    if not cfg['enabled'] or not cfg['host']:
        return {'success': False, 'error': 'NAS upload disabled'}

    if media_dir is None:
        from flask import current_app
        media_dir = current_app.config.get('WA_UPLOADS_FOLDER', 'uploads/wa-media')

    local_file = _get_local_path(local_web_path, media_dir)
    if not os.path.isfile(local_file):
        return {'success': False, 'error': f'File not found: {local_file}'}

    from app.services.nas_site_remark_service import hk_today_str

    filename = os.path.basename(local_file)
    day = day_str or hk_today_str()
    remote_dir = _remote_photo_day_dir(cfg['base_dir'], project_code, day)
    remote_path = f'{remote_dir}/{filename}'

    for attempt in range(1, MAX_RETRIES + 1):
        transport = None
        sftp = None
        try:
            transport = paramiko.Transport((cfg['host'], cfg['port']))
            transport.connect(username=cfg['user'], password=cfg['password'])
            sftp = paramiko.SFTPClient.from_transport(transport)

            _ensure_remote_dir(sftp, remote_dir)
            sftp.put(local_file, remote_path)

            logger.info('[NAS] Uploaded: %s (attempt %d)', remote_path, attempt)
            return {'success': True, 'nas_path': remote_path}
        except Exception as e:
            logger.error('[NAS] Attempt %d/%d failed: %s', attempt, MAX_RETRIES, e)
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY * attempt)
            else:
                return {'success': False, 'error': str(e)}
        finally:
            if sftp:
                sftp.close()
            if transport:
                transport.close()

    return {'success': False, 'error': 'Exhausted retries'}


def upload_batch_to_nas(local_web_paths, project_code, media_dir=None, *, day_str=None):
    cfg = _get_config()
    if not cfg['enabled'] or not cfg['host'] or not local_web_paths:
        return [{'success': False, 'error': 'NAS disabled'} for _ in local_web_paths]

    if media_dir is None:
        from flask import current_app
        media_dir = current_app.config.get('WA_UPLOADS_FOLDER', 'uploads/wa-media')

    results = []
    transport = None
    sftp = None
    try:
        transport = paramiko.Transport((cfg['host'], cfg['port']))
        transport.connect(username=cfg['user'], password=cfg['password'])
        sftp = paramiko.SFTPClient.from_transport(transport)

        from app.services.nas_site_remark_service import hk_today_str

        day = day_str or hk_today_str()
        remote_dir = _remote_photo_day_dir(cfg['base_dir'], project_code, day)
        _ensure_remote_dir(sftp, remote_dir)

        for web_path in local_web_paths:
            local_file = _get_local_path(web_path, media_dir)
            if not os.path.isfile(local_file):
                results.append({'success': False, 'error': f'File not found: {local_file}'})
                continue
            filename = os.path.basename(local_file)
            remote_path = f'{remote_dir}/{filename}'
            try:
                sftp.put(local_file, remote_path)
                logger.info('[NAS] Uploaded: %s', remote_path)
                results.append({'success': True, 'nas_path': remote_path})
            except Exception as e:
                logger.error('[NAS] Failed %s: %s', filename, e)
                results.append({'success': False, 'error': str(e)})
    except Exception as e:
        logger.error('[NAS] Connection failed: %s', e)
        return [{'success': False, 'error': str(e)} for _ in local_web_paths]
    finally:
        if sftp:
            sftp.close()
        if transport:
            transport.close()

    return results
