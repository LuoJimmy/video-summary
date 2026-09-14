from fastapi import APIRouter, BackgroundTasks, HTTPException

from app.schemas import PluginOut
from app.services.plugins import (
    PLUGIN_IDS,
    PluginError,
    cancel_plugin_install,
    describe_plugin,
    install_plugin,
    list_plugins,
    mark_plugin_install_started,
    plugins_root,
    uninstall_plugin,
)

router = APIRouter(prefix="/api/plugins", tags=["plugins"])


def _out(info) -> PluginOut:
    return PluginOut(
        id=info.id,
        title=info.title,
        description=info.description,
        size_hint=info.size_hint,
        status=info.status,
        error=info.error,
        soffice=info.soffice,
    )


@router.get("", response_model=list[PluginOut])
def get_plugins() -> list[PluginOut]:
    return [_out(item) for item in list_plugins()]


@router.post("/{plugin_id}/install", response_model=PluginOut)
def install(plugin_id: str, background: BackgroundTasks) -> PluginOut:
    if plugin_id not in PLUGIN_IDS:
        raise HTTPException(404, "插件不存在")
    info = describe_plugin(plugin_id)
    if info.status in {"installing", "ready"}:
        return _out(info)
    lock_path = plugins_root() / f".{plugin_id}.lock"
    mark_plugin_install_started(plugin_id)
    lock_path.write_text("queued", encoding="utf-8")
    background.add_task(_install, plugin_id)
    return _out(describe_plugin(plugin_id))


@router.post("/{plugin_id}/cancel", response_model=PluginOut)
def cancel_install(plugin_id: str) -> PluginOut:
    if plugin_id not in PLUGIN_IDS:
        raise HTTPException(404, "插件不存在")
    try:
        return _out(cancel_plugin_install(plugin_id))
    except PluginError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/{plugin_id}/uninstall", response_model=PluginOut)
def uninstall(plugin_id: str) -> PluginOut:
    if plugin_id not in PLUGIN_IDS:
        raise HTTPException(404, "插件不存在")
    try:
        uninstall_plugin(plugin_id)
    except PluginError as exc:
        raise HTTPException(409, str(exc)) from exc
    return _out(describe_plugin(plugin_id))


def _install(plugin_id: str) -> None:
    try:
        install_plugin(plugin_id)
    except PluginError:
        return
