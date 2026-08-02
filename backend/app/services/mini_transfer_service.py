"""Mac Mini SCP transfer service — sends media files to a remote Mac Mini."""
import os
import subprocess
import logging

logger = logging.getLogger(__name__)


def _get_config():
    from flask import current_app
    ssh_key = current_app.config.get('MINI_SSH_KEY', '~/.ssh/id_ed25519')
    if ssh_key.startswith('~'):
        ssh_key = os.path.expanduser(ssh_key)
    return {
        'host': current_app.config.get('MINI_HOST', ''),
        'user': current_app.config.get('MINI_USER', ''),
        'ssh_key': ssh_key,
        'dest_dir': current_app.config.get('MINI_DEST_DIR', '~/Desktop/whats app'),
        'enabled': current_app.config.get('MINI_ENABLED', False),
        'target_group': current_app.config.get('MINI_TARGET_GROUP_ID', ''),
    }


def _shell_escape_path(p):
    """Escape spaces for shell, but keep ~ unquoted for expansion."""
    if p.startswith('~/'):
        return '~/' + p[2:].replace(' ', '\\ ')
    return p.replace(' ', '\\ ')


def _ssh_opts(cfg):
    return f'-o StrictHostKeyChecking=no -o IdentitiesOnly=yes -i "{cfg["ssh_key"]}" -o ConnectTimeout=10'


def _ssh_exec(cmd, cfg):
    full = f'ssh {_ssh_opts(cfg)} {cfg["user"]}@{cfg["host"]} \'{cmd}\''
    result = subprocess.run(full, shell=True, capture_output=True, text=True, timeout=15)
    if result.returncode != 0:
        raise RuntimeError(f'SSH command failed: {result.stderr.strip()}')
    return result.stdout.strip()


def _scp_file(local_path, remote_path, cfg):
    escaped = _shell_escape_path(remote_path)
    cmd = f'scp {_ssh_opts(cfg)} "{local_path}" {cfg["user"]}@{cfg["host"]}:{escaped}'
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(f'SCP failed: {result.stderr.strip()}')


def is_mini_enabled():
    try:
        cfg = _get_config()
        return cfg['enabled'] and bool(cfg['host'])
    except RuntimeError:
        return False


def is_target_group(group_id):
    try:
        cfg = _get_config()
        return cfg['enabled'] and group_id == cfg['target_group']
    except RuntimeError:
        return False


def _get_local_path(web_path, media_dir):
    relative = web_path.lstrip('/').replace('uploads/', '', 1)
    return os.path.join(media_dir, relative)


def transfer_to_mini(local_web_path, project_code, media_dir=None):
    cfg = _get_config()
    if not cfg['enabled'] or not cfg['host']:
        return {'success': False, 'error': 'Mini transfer disabled'}

    if media_dir is None:
        from flask import current_app
        media_dir = current_app.config.get('WA_UPLOADS_FOLDER', 'uploads/wa-media')

    local_file = _get_local_path(local_web_path, media_dir)
    if not os.path.isfile(local_file):
        return {'success': False, 'error': f'File not found: {local_file}'}

    remote_dir = f'{cfg["dest_dir"]}/{project_code}'
    filename = os.path.basename(local_file)
    remote_path = f'{remote_dir}/{filename}'

    try:
        _ssh_exec(f'mkdir -p {_shell_escape_path(remote_dir)}', cfg)
        _scp_file(local_file, remote_path, cfg)
        logger.info('[Mini] Transferred: %s', remote_path)
        return {'success': True, 'remote_path': remote_path}
    except Exception as e:
        logger.error('[Mini] Transfer failed for %s: %s', filename, e)
        return {'success': False, 'error': str(e)}


def transfer_batch_to_mini(local_web_paths, project_code, media_dir=None):
    cfg = _get_config()
    if not cfg['enabled'] or not cfg['host'] or not local_web_paths:
        return [{'success': False, 'error': 'Mini disabled'} for _ in local_web_paths]

    if media_dir is None:
        from flask import current_app
        media_dir = current_app.config.get('WA_UPLOADS_FOLDER', 'uploads/wa-media')

    remote_dir = f'{cfg["dest_dir"]}/{project_code}'
    try:
        _ssh_exec(f'mkdir -p {_shell_escape_path(remote_dir)}', cfg)
    except Exception as e:
        logger.error('[Mini] Failed to create remote dir: %s', e)
        return [{'success': False, 'error': str(e)} for _ in local_web_paths]

    results = []
    for web_path in local_web_paths:
        local_file = _get_local_path(web_path, media_dir)
        if not os.path.isfile(local_file):
            results.append({'success': False, 'error': f'File not found: {local_file}'})
            continue
        filename = os.path.basename(local_file)
        remote_path = f'{remote_dir}/{filename}'
        try:
            _scp_file(local_file, remote_path, cfg)
            logger.info('[Mini] Transferred: %s', remote_path)
            results.append({'success': True, 'remote_path': remote_path})
        except Exception as e:
            logger.error('[Mini] Failed %s: %s', filename, e)
            results.append({'success': False, 'error': str(e)})

    return results
