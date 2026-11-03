"""stdio MCP server exposing Sign House WhatsApp REST capabilities."""
from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from mcp_wa.client import SignHouseApiError, SignHouseClient, json_result, uploads_url

mcp = FastMCP(
    'sign-house-wa',
    stateless_http=True,
    streamable_http_path='/',
    sse_path='/sse',
    message_path='/messages/',
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=False,
    ),
)


def _client() -> SignHouseClient:
    return SignHouseClient()


@mcp.tool()
def wa_whoami() -> str:
    """Return the current Sign House user (validates SIGN_HOUSE_JWT)."""
    try:
        return json_result(_client().get('/auth/me'))
    except SignHouseApiError as exc:
        return str(exc)


@mcp.tool()
def wa_get_dashboard_stats() -> str:
    """WA dashboard intake/completion counters."""
    try:
        return json_result(_client().get('/wa/dashboard/stats'))
    except SignHouseApiError as exc:
        return str(exc)


@mcp.tool()
def wa_get_recent_records() -> str:
    """Latest WA records for dashboard."""
    try:
        return json_result(_client().get('/wa/dashboard/recent'))
    except SignHouseApiError as exc:
        return str(exc)


@mcp.tool()
def wa_search_records(
    q: str = '',
    status: str = '',
    phone: str = '',
    project: str = '',
    from_date: str = '',
    to_date: str = '',
    page: int = 1,
    limit: int = 50,
) -> str:
    """Search WA records. Dates ISO format. status comma-separated."""
    try:
        params = {
            'q': q,
            'status': status,
            'phone': phone,
            'project': project,
            'from': from_date,
            'to': to_date,
            'page': page,
            'limit': limit,
        }
        return json_result(_client().get('/wa/search', params=params))
    except SignHouseApiError as exc:
        return str(exc)


@mcp.tool()
def wa_list_projects(status: str = '') -> str:
    """List WA projects (optional status filter)."""
    try:
        return json_result(_client().get('/wa/projects', params={'status': status or None}))
    except SignHouseApiError as exc:
        return str(exc)


@mcp.tool()
def wa_get_project(project_id: str, include_nas_files: bool = False) -> str:
    """Get one WA project by Mongo id."""
    try:
        params = {'includeNasFiles': '1' if include_nas_files else None}
        return json_result(_client().get(f'/wa/projects/{project_id}', params=params))
    except SignHouseApiError as exc:
        return str(exc)


@mcp.tool()
def wa_list_project_records(
    project_id: str,
    status: str = '',
    record_type: str = '',
    phone: str = '',
    page: int = 1,
    limit: int = 50,
    include_voided: bool = False,
) -> str:
    """Paginated records for a WA project."""
    try:
        params = {
            'status': status or None,
            'type': record_type or None,
            'phone': phone or None,
            'page': page,
            'limit': limit,
            'includeVoided': '1' if include_voided else None,
        }
        return json_result(_client().get(f'/wa/projects/{project_id}/records', params=params))
    except SignHouseApiError as exc:
        return str(exc)


@mcp.tool()
def wa_get_record(record_id: str) -> str:
    """Get full WA record by id."""
    try:
        return json_result(_client().get(f'/wa/records/{record_id}'))
    except SignHouseApiError as exc:
        return str(exc)


@mcp.tool()
def wa_update_record_field(record_id: str, field: str, value: str) -> str:
    """Patch one extracted field on a WA record."""
    try:
        return json_result(_client().patch(f'/wa/records/{record_id}', json_body={'field': field, 'value': value}))
    except SignHouseApiError as exc:
        return str(exc)


@mcp.tool()
def wa_confirm_record(record_id: str) -> str:
    """Mark WA record completed."""
    try:
        return json_result(_client().post(f'/wa/records/{record_id}/confirm'))
    except SignHouseApiError as exc:
        return str(exc)


@mcp.tool()
def wa_void_record(record_id: str, reason: str) -> str:
    """Void WA record (reason min 5 chars)."""
    try:
        return json_result(_client().post(f'/wa/records/{record_id}/void', json_body={'reason': reason}))
    except SignHouseApiError as exc:
        return str(exc)


@mcp.tool()
def wa_request_record_info(record_id: str, question: str) -> str:
    """Send WhatsApp follow-up question for a record."""
    try:
        return json_result(
            _client().post(f'/wa/records/{record_id}/request-info', json_body={'question': question})
        )
    except SignHouseApiError as exc:
        return str(exc)


@mcp.tool()
def wa_get_pool_stats() -> str:
    """Unassigned/assigned media pool statistics."""
    try:
        return json_result(_client().get('/wa/image-pool', params={'mode': 'stats'}))
    except SignHouseApiError as exc:
        return str(exc)


@mcp.tool()
def wa_list_pool_images(
    status: str = 'unassigned',
    phone: str = '',
    project: str = '',
    page: int = 1,
    limit: int = 50,
) -> str:
    """List media pool images (status: unassigned | assigned)."""
    try:
        params = {'status': status, 'phone': phone or None, 'project': project or None, 'page': page, 'limit': limit}
        return json_result(_client().get('/wa/image-pool', params=params))
    except SignHouseApiError as exc:
        return str(exc)


@mcp.tool()
def wa_assign_pool_images(
    image_ids: list[str],
    project_id: str,
    group_id: str = '',
    notify_whatsapp: bool = False,
    nas_folder_name: str = '',
    nas_parent_bucket: str = '',
    remark: str = '',
) -> str:
    """Assign pool images to an active WA project and optionally write the site remark.

    When the user includes a note (备注、備註、caption after the project code, e.g. 「歸到 1005 備註是 Test」),
    pass that note as remark — the note text only, without the project code or the words 备注/備註.
    remark is stored on the WA record and written to NAS as Photo/YYYY-MM-DD/<site-folder>_YYYY-MM-DD.txt.
    siteRemarkQueued in the result means a remark was accepted for NAS write (async after photos copy).
    Do not tell the user a remark or txt was saved when siteRemarkQueued is false or assigned is 0.
    Never use wa_update_record_field to store classify remarks — that does not create the day .txt file.
    When notify_whatsapp is true, send a short 繁中 confirmation to group_id after assign.
    For duplicate NAS site folders, pass nas_folder_name (and optional nas_parent_bucket).
    In group chats always pass group_id (@g.us JID) and only image_ids from wa_list_pool_images
    filtered by that sender's phone — the API rejects mixed senders or mixed batches.
    """
    try:
        body = {
            'imageIds': image_ids,
            'projectId': project_id,
            'notifyWhatsApp': bool(notify_whatsapp),
        }
        if group_id.strip():
            body['groupId'] = group_id.strip()
        if nas_folder_name.strip():
            body['nasFolderName'] = nas_folder_name.strip()
        if nas_parent_bucket.strip():
            body['nasParentBucket'] = nas_parent_bucket.strip()
        if remark.strip():
            body['remark'] = remark.strip()
        return json_result(_client().post('/wa/image-pool/assign', json_body=body))
    except SignHouseApiError as exc:
        return str(exc)


@mcp.tool()
def wa_append_site_remark(
    project_code: str,
    text: str,
    nas_folder_name: str = '',
    nas_parent_bucket: str = '',
    phone: str = '',
    day: str = '',
) -> str:
    """Append an on-site note to the NAS day remark file after photos were already filed.

    Writes Photo/YYYY-MM-DD/<site-folder>_YYYY-MM-DD.txt (same file as classify-time remarks).
    Use when the user adds or corrects a note after wa_assign_pool_images, and that call
    did not include remark. Pass the same nas_folder_name / nas_parent_bucket used at assign
    when the site folder is not unique. text is the note only.
    """
    try:
        body: dict[str, Any] = {
            'projectCode': project_code.strip(),
            'text': text.strip(),
        }
        if nas_folder_name.strip():
            body['nasFolderName'] = nas_folder_name.strip()
        if nas_parent_bucket.strip():
            body['nasParentBucket'] = nas_parent_bucket.strip()
        if phone.strip():
            body['phone'] = phone.strip()
        if day.strip():
            body['day'] = day.strip()
        return json_result(_client().post('/wa/image-pool/site-remark', json_body=body))
    except SignHouseApiError as exc:
        return str(exc)


@mcp.tool()
def wa_retry_pool_download(image_ids: list[str]) -> str:
    """Retry Wakka download for pool images."""
    try:
        return json_result(_client().post('/wa/image-pool/retry-download', json_body={'imageIds': image_ids}))
    except SignHouseApiError as exc:
        return str(exc)


@mcp.tool()
def wa_delete_pool_images(image_ids: list[str]) -> str:
    """Delete images from the media pool."""
    try:
        return json_result(_client().post('/wa/image-pool/delete', json_body={'imageIds': image_ids}))
    except SignHouseApiError as exc:
        return str(exc)


@mcp.tool()
def wa_list_keywords() -> str:
    """List WA classify keywords (requires admin or manager)."""
    try:
        return json_result(_client().get('/wa/admin/keywords'))
    except SignHouseApiError as exc:
        return str(exc)


@mcp.tool()
def wa_create_keyword(term: str, keyword_type: str, synonyms: list[str] | None = None) -> str:
    """Create keyword (admin only)."""
    try:
        body = {'term': term, 'type': keyword_type, 'synonyms': synonyms or []}
        return json_result(_client().post('/wa/admin/keywords', json_body=body))
    except SignHouseApiError as exc:
        return str(exc)


@mcp.tool()
def wa_delete_keyword(keyword_id: str) -> str:
    """Delete keyword by id (admin only)."""
    try:
        return json_result(_client().delete('/wa/admin/keywords', params={'id': keyword_id}))
    except SignHouseApiError as exc:
        return str(exc)


@mcp.tool()
def wa_list_templates() -> str:
    """List WA field templates (admin only)."""
    try:
        return json_result(_client().get('/wa/admin/templates'))
    except SignHouseApiError as exc:
        return str(exc)


@mcp.tool()
def wa_create_template(type_name: str, fields: list[dict[str, Any]] | None = None) -> str:
    """Create WA template (admin only). fields: list of {name, type, required}."""
    try:
        return json_result(
            _client().post('/wa/admin/templates', json_body={'typeName': type_name, 'fields': fields or []})
        )
    except SignHouseApiError as exc:
        return str(exc)


@mcp.tool()
def wa_move_record_to_project(
    record_reference: str,
    project_code: str,
    nas_folder_name: str = '',
    nas_parent_bucket: str = '',
    relocate_nas: bool = True,
) -> str:
    """Move an already-filed WA record (all pool photos) to another project.

    record_reference is SUB-xxxx-xxx or Mongo record id. Removes NAS photo + day .txt files
    from the old site after copy succeeds; merges remark text into the new project's
    Photo/<day>/<folder>_<day>.txt (relocate_nas=true).
    Target must exist in wa_projects (e.g. PJ-3014A). Pass nas_folder_name when duplicate folders.
    """
    try:
        body: dict[str, Any] = {
            'recordReference': record_reference.strip(),
            'targetProjectCode': project_code.strip(),
            'relocateNas': bool(relocate_nas),
        }
        if nas_folder_name.strip():
            body['nasFolderName'] = nas_folder_name.strip()
        if nas_parent_bucket.strip():
            body['nasParentBucket'] = nas_parent_bucket.strip()
        return json_result(_client().post('/wa/image-pool/move', json_body=body))
    except SignHouseApiError as exc:
        return str(exc)


@mcp.tool()
def wa_create_project(
    code: str,
    name: str,
    location: str = '',
    stage: str = 'active',
    parent_bucket_code: str = '',
) -> str:
    """Create WA project (admin/manager). name is required (use NAS folder display name).

    Under a NAS bucket (standalone or range), pass parent_bucket_code and use a *child*
    site code — never the same name as the bucket root (e.g. not KTEST under KTEST).

    Do not use for a mistyped site number: if wa_list_projects shows nearby codes
    (e.g. user said 1008 but 1005/1007 exist), ask the user first instead of creating."""
    try:
        body: dict = {'code': code, 'name': name, 'location': location, 'stage': stage}
        if parent_bucket_code.strip():
            body['parentBucketCode'] = parent_bucket_code.strip()
        return json_result(_client().post('/wa/admin/projects', json_body=body))
    except SignHouseApiError as exc:
        return str(exc)


@mcp.tool()
def wa_delete_project(project_id: str, delete_nas_folder: bool | None = None) -> str:
    """Delete WA project (admin only)."""
    try:
        body: dict[str, Any] = {}
        if delete_nas_folder is not None:
            body['deleteNasFolder'] = delete_nas_folder
        return json_result(_client().call('DELETE', f'/wa/admin/projects/{project_id}', json_body=body or None))
    except SignHouseApiError as exc:
        return str(exc)


@mcp.tool()
def wa_get_whatsapp_status() -> str:
    """Wakka session / connection status (admin only)."""
    try:
        return json_result(_client().get('/wa/admin/system/status'))
    except SignHouseApiError as exc:
        return str(exc)


@mcp.tool()
def wa_get_infra_status() -> str:
    """Mongo and Ollama health (admin only)."""
    try:
        return json_result(_client().get('/wa/admin/system/infra'))
    except SignHouseApiError as exc:
        return str(exc)


@mcp.tool()
def wa_get_nas_status() -> str:
    """NAS mount status for WA."""
    try:
        return json_result(_client().get('/wa/nas/status'))
    except SignHouseApiError as exc:
        return str(exc)


@mcp.tool()
def wa_sync_nas_bidirectional() -> str:
    """Full NAS ↔ app sync (admin/manager). Slow; do not run concurrently."""
    try:
        return json_result(_client().long_post('/wa/nas/sync-bidirectional'))
    except SignHouseApiError as exc:
        return str(exc)


@mcp.tool()
def wa_browse_nas(code: str = '') -> str:
    """List NAS folders or files under a project code."""
    try:
        return json_result(_client().get('/wa/nas/browse', params={'code': code or None}))
    except SignHouseApiError as exc:
        return str(exc)


@mcp.tool()
def wa_create_nas_folder(code: str) -> str:
    """Create NAS folder for project code (admin/manager)."""
    try:
        return json_result(_client().post('/wa/nas/create-folder', json_body={'code': code}))
    except SignHouseApiError as exc:
        return str(exc)


@mcp.tool()
def wa_sync_nas_projects() -> str:
    """Create web projects for NAS folders not yet in Mongo (admin/manager)."""
    try:
        return json_result(_client().long_post('/wa/nas/sync-projects'))
    except SignHouseApiError as exc:
        return str(exc)


@mcp.tool()
def wa_import_nas_files(project_id: str) -> str:
    """Import NAS images into records for one project (admin/manager)."""
    try:
        return json_result(_client().long_post('/wa/nas/import-files', json_body={'projectId': project_id}))
    except SignHouseApiError as exc:
        return str(exc)


@mcp.tool()
def wa_import_nas_all() -> str:
    """Import NAS images for all active projects (admin/manager)."""
    try:
        return json_result(_client().long_post('/wa/nas/import-all'))
    except SignHouseApiError as exc:
        return str(exc)


@mcp.tool()
def wa_relocate_nas_site_folder(
    site_folder_name: str,
    source_parent_bucket: str,
    target_parent_bucket: str,
    dry_run: bool = False,
) -> str:
    """Move a site NAS folder to another bucket parent (admin/manager).

    Example: move kelly from KTEST2 to KTEST — updates wa_projects and record NAS paths.
    Use dry_run=true to preview paths without moving files.
    """
    try:
        body = {
            'siteFolderName': site_folder_name.strip(),
            'sourceParentBucket': source_parent_bucket.strip(),
            'targetParentBucket': target_parent_bucket.strip(),
            'dryRun': bool(dry_run),
        }
        return json_result(_client().post('/wa/nas/relocate-site-folder', json_body=body))
    except SignHouseApiError as exc:
        return str(exc)


@mcp.tool()
def wa_relocate_nas_bucket_children(
    source_parent_bucket: str,
    target_parent_bucket: str,
    dry_run: bool = False,
) -> str:
    """Move every site subfolder from one bucket to another (admin/manager).

    Example: KTEST2/K-1000 and KTEST2/kelly → under KTEST/. dry_run previews only.
    """
    try:
        body = {
            'sourceParentBucket': source_parent_bucket.strip(),
            'targetParentBucket': target_parent_bucket.strip(),
            'dryRun': bool(dry_run),
        }
        return json_result(_client().post('/wa/nas/relocate-bucket-children', json_body=body))
    except SignHouseApiError as exc:
        return str(exc)


@mcp.tool()
def wa_send_message(to: str, message: str, quoted_msg_id: str = '') -> str:
    """Send WhatsApp private text via Wakka."""
    try:
        body: dict[str, Any] = {'type': 'text', 'to': to, 'message': message}
        if quoted_msg_id:
            body['quotedMsgId'] = quoted_msg_id
        return json_result(_client().post('/wa/outbound', json_body=body))
    except SignHouseApiError as exc:
        return str(exc)


@mcp.tool()
def wa_send_media(to: str, media_url: str, caption: str = '', filename: str = '') -> str:
    """Send WhatsApp private media URL via Wakka."""
    try:
        body: dict[str, Any] = {'type': 'media', 'to': to, 'mediaUrl': media_url}
        if caption:
            body['caption'] = caption
        if filename:
            body['filename'] = filename
        return json_result(_client().post('/wa/outbound', json_body=body))
    except SignHouseApiError as exc:
        return str(exc)


@mcp.tool()
def wa_send_group_message(
    group_id: str,
    message: str,
    media_url: str = '',
    quoted_msg_id: str = '',
) -> str:
    """Send WhatsApp group message (optional media URL)."""
    try:
        body: dict[str, Any] = {'type': 'group', 'groupId': group_id, 'message': message}
        if media_url:
            body['mediaUrl'] = media_url
        if quoted_msg_id:
            body['quotedMsgId'] = quoted_msg_id
        return json_result(_client().post('/wa/outbound', json_body=body))
    except SignHouseApiError as exc:
        return str(exc)


@mcp.tool()
def wa_media_path_hint(record_id: str = '', pool_image_id: str = '') -> str:
    """
    Return fetchable URLs for WA media (no binary). Provide record_id or pool_image_id.
    Requires JWT; use browser or WebFetch with the same auth if needed.
    """
    try:
        client = _client()
        urls: list[str] = []
        if record_id:
            rec = client.get(f'/wa/records/{record_id}')
            for p in rec.get('photos') or []:
                u = uploads_url(str(p))
                if u:
                    urls.append(u)
        if pool_image_id:
            data = client.get('/wa/image-pool', params={'status': 'unassigned', 'limit': 200})
            images = data.get('images') or []
            match = next((i for i in images if str(i.get('id')) == pool_image_id), None)
            if not match:
                data = client.get('/wa/image-pool', params={'status': 'assigned', 'limit': 200})
                images = data.get('images') or []
                match = next((i for i in images if str(i.get('id')) == pool_image_id), None)
            if match and match.get('imagePath'):
                urls.append(uploads_url(str(match['imagePath'])))
            elif pool_image_id and not match:
                return f'Pool image {pool_image_id} not found in first 200 unassigned/assigned results.'
        if not record_id and not pool_image_id:
            return 'Provide record_id or pool_image_id.'
        if not urls:
            return 'No media paths on this item.'
        return json_result({'urls': urls})
    except SignHouseApiError as exc:
        return str(exc)


def main() -> None:
    mcp.run()


if __name__ == '__main__':
    main()
