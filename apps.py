from dataclasses import dataclass
from typing import Optional


@dataclass
class AppConfig:
    name: str
    package_name: str
    # Mirror sources skip an app without their config; an app without a patcher is downloaded but not patched
    apkmirror_app_id: Optional[str] = None
    apkmirror_url_template: Optional[str] = None
    apkpure_app_path: Optional[str] = None
    patcher_name: Optional[str] = None


APPS = [
    AppConfig(
        name="WhatsApp Messenger",
        package_name="com.whatsapp",
        apkmirror_app_id="whatsapp-messenger",
        apkmirror_url_template="/apk/whatsapp-inc/whatsapp-messenger/whatsapp-messenger-{}-release/",
        apkpure_app_path="whatsapp-android/com.whatsapp",
        patcher_name="WhatsAppPatcher"
    ),
    AppConfig(
        name='Moovit',
        package_name='com.tranzmate',
        apkmirror_app_id='moovit-bus-train-live-info',
        apkmirror_url_template='/apk/moovit/moovit-bus-train-live-info/moovit-your-transit-tracker-{}-release/',
        apkpure_app_path='moovit-bus-train-schedules/com.tranzmate',
        patcher_name='MoovitPatcher'
    ),
    AppConfig(
        name='12+',
        package_name='com.keshet.mako.VOD',
        apkmirror_app_id='makotv',
        apkmirror_url_template='/apk/keshet-broadcasting-ltd/makotv/makotv-{}-release/',
        apkpure_app_path='12/com.keshet.mako.VOD'
        , patcher_name='MakoPatcher'
    ),
    AppConfig(
        name='OkCupid',
        package_name='com.okcupid.okcupid',
        patcher_name='OkCupidPatcher',
    ),
]
