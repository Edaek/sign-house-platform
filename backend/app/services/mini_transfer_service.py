"""Mac Mini transfer service — copies media to a local folder or sends via SCP."""
import os
import shutil
import subprocess
import logging

logger = logging.getLogger(__name__)


def _get_config():
    from flask import current_app
    ssh_key = current_app.config.get('MINI_SSH_KEY', '~/.ssh/id_ed25519')
    if ssh_key.startswith('~'):
        ssh_key = os.path.expanduser(ssh_key)
    dest_dir = current_app.config.get('MINI_DEST_DIR', '~/Desktop/whats app')
    if dest_dir.startswith('~'):
        dest_dir = os.path.expanduser(dest_dir)
    return {
        'host': current_app.config.get('MINI_HOST', ''),
        'user': current_app.config.get('MINI_USER', ''),
        'ssh_key': ssh_key,
        'dest_dir': dest_dir,
        'enabled': current_app.config.get('MINI_ENABLED', False),
        'local': current_app.config.get('MINI_LOCAL', False),
        'target_group': current_app.config.get('MINI_TARGET_GROUP_ID', ''),
    }


def _shell_escape_path(p):
    """Escape spaces for shell, but keep ~ unquoted for expansion."""
    if p.startswith('~/'):
        return '~/' + p[2:].replace(' ', '\\ ')
    return p.replace(' ', '\\ ')


def _ssh_opts(cfg):
    return '-o StrictHostKeyChecking=no -o IdentitiesOnly=yes -i "{}" -o ConnectTimeout=10'.format(cfg["ssh_key"])


def _ssh_exec(cmd, cfg):
    full = 'ssh {} {}@{} \'{}\''.format(_ssh_opts(cfg), cfg["user"], cfg["host"], cmd)
    result = subprocess.run(full, shell=True, capture_output=True, text=True, timeout=15)
    if result.returncode != 0:
        raise RuntimeError('SSH command failed: {}'.format(result.stderr.strip()))
    return result.stdout.strip()


def _scp_file(local_path, remote_path, cfg):
    escaped = _shell_escape_path(remote_path)
    cmd = 'scp {} "{}" {}@{}:{}'.format(_ssh_opts(cfg), local_path, cfg["user"], cfg["host"], escaped)
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError('SCP failed: {}'.format(result.stderr.strip()))


def _local_copy(local_file, dest_dir, project_code):
    """Copy file to a local destination folder."""
    target_dir = os.path.join(dest_dir, project_code)
    os.makedirs(target_dir, exist_ok=True)
    filename = os.path.basename(local_file)
    target_path = os.path.join(target_dir, filename)
    shutil.copy2(local_file, target_path)
    logger.info('[Mini:Local] Copied: %s -> %s', local_file, target_path)
    return target_path


def is_mini_enabled():
    try:
        cfg = _get_config()
        if cfg['local']:
            return cfg['enabled']
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
    """Resolve a web path like /uploads/wa-media/xxx.jpg to a local file path."""
    relative = web_path.lstrip('/')
    if relative.startswith('uploads/'):
        relative = relative[len('uploads/'):]
    if relative.startswith('wa-media/'):
        relative = relative[len('wa-media/'):]
    return os.path.join(media_dir, relative)


def transfer_to_mini(local_web_path, project_code, media_dir=None):
    cfg = _get_config()
    if not cfg['enabled']:
        return {'success': False, 'error': 'Mini transfer disabled'}

    if media_dir is None:
        from flask import current_app
        media_dir = current_app.config.get('WA_UPLOADS_FOLDER', 'uploads/wa-media')

    local_file = _get_local_path(local_web_path, media_dir)
    if not os.path.isfile(local_file):
        return {'success': False, 'error': 'File not found: {}'.format(local_file)}

    if cfg['local']:
        try:
            target = _local_copy(local_file, cfg['dest_dir'], project_code)
            return {'success': True, 'remote_path': target}
        except Exception as e:
            logger.error('[Mini:Local] Copy failed for %s: %s', local_file, e)
            return {'success': False, 'error': str(e)}

    if not cfg['host']:
        return {'success': False, 'error': 'MINI_HOST not configured'}

    remote_dir = '{}/{}'.format(cfg['dest_dir'], project_code)
    filename = os.path.basename(local_file)
    remote_path = '{}/{}'.format(remote_dir, filename)

    try:
        _ssh_exec('mkdir -p {}'.format(_shell_escape_path(remote_dir)), cfg)
        _scp_file(local_file, remote_path, cfg)
        logger.info('[Mini] Transferred: %s', remote_path)
        return {'success': True, 'remote_path': remote_path}
    except Exception as e:
        logger.error('[Mini] Transfer failed for %s: %s', filename, e)
        return {'success': False, 'error': str(e)}


def transfer_batch_to_mini(local_web_paths, project_code, media_dir=None):
    cfg = _get_config()
    if not cfg['enabled'] or not local_web_paths:
        return [{'success': False, 'error': 'Mini disabled'} for _ in local_web_paths]

    if media_dir is None:
        from flask import current_app
        media_dir = current_app.config.get('WA_UPLOADS_FOLDER', 'uploads/wa-media')

    if cfg['local']:
        results = []
        for web_path in local_web_paths:
            local_file = _get_local_path(web_path, media_dir)
            if not os.path.isfile(local_file):
                results.append({'success': False, 'error': 'File not found: {}'.format(local_file)})
                continue
            try:
                target = _local_copy(local_file, cfg['dest_dir'], project_code)
                results.append({'success': True, 'remote_path': target})
            except Exception as e:
                logger.error('[Mini:Local] Copy failed %s: %s', local_file, e)
                results.append({'success': False, 'error': str(e)})
        return results

    if not cfg['host']:
        return [{'success': False, 'error': 'MINI_HOST not configured'} for _ in local_web_paths]

    remote_dir = '{}/{}'.format(cfg['dest_dir'], project_code)
    try:
        _ssh_exec('mkdir -p {}'.format(_shell_escape_path(remote_dir)), cfg)
    except Exception as e:
        logger.error('[Mini] Failed to create remote dir: %s', e)
        return [{'success': False, 'error': str(e)} for _ in local_web_paths]

    results = []
    for web_path in local_web_paths:
        local_file = _get_local_path(web_path, media_dir)
        if not os.path.isfile(local_file):
            results.append({'success': False, 'error': 'File not found: {}'.format(local_file)})
            continue
        filename = os.path.basename(local_file)
        remote_path = '{}/{}'.format(remote_dir, filename)
        try:
            _scp_file(local_file, remote_path, cfg)
            logger.info('[Mini] Transferred: %s', remote_path)
            results.append({'success': True, 'remote_path': remote_path})
        except Exception as e:
            logger.error('[Mini] Failed %s: %s', filename, e)
            results.append({'success': False, 'error': str(e)})

    return results
