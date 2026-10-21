from dataclasses import dataclass
from typing import FrozenSet, Optional


@dataclass
class AppConfig:
    name: str
    package_name: str
    # Mirror sources skip an app without their config; an app without a patcher is downloaded but not patched
    apkmirror_app_id: Optional[str] = None
    apkmirror_url_template: Optional[str] = None
    apkpure_app_path: Optional[str] = None
    patcher_name: Optional[str] = None
    # "build" downloads and patches new releases; "artifacts" records the app's signature-finder result
    pipelines: FrozenSet[str] = frozenset({"build"})
    # A fixed URL always serving the current APK, and the source name records from it carry
    direct_url: Optional[str] = None
    direct_source: Optional[str] = None


APPS = [
    AppConfig(
        name="WhatsApp Messenger",
        package_name="com.whatsapp",
        apkmirror_app_id="whatsapp-messenger",
        apkmirror_url_template="/apk/whatsapp-inc/whatsapp-messenger/whatsapp-messenger-{}-release/",
        apkpure_app_path="whatsapp-android/com.whatsapp",
        patcher_name="WhatsAppPatcher",
        pipelines=frozenset({"build", "artifacts"}),
        direct_url="https://www.whatsapp.com/android/current/WhatsApp.apk",
        direct_source="whatsapp.com",
    ),
]
