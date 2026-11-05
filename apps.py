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
    # The slug is רשת-13-צפייה-בכל-תוכניות-רשת, encoded in lowercase as APKMirror writes it in its links
    AppConfig(
        name='Reshet 13',
        package_name='com.applicaster.iReshet',
        apkmirror_app_id='%d7%a8%d7%a9%d7%aa-13-%d7%a6%d7%a4%d7%99%d7%99%d7%94-%d7%91%d7%9b%d7%9c-%d7%aa%d7%95%d7%9b%d7%a0%d7%99%d7%95%d7%aa-%d7%a8%d7%a9%d7%aa',
        apkmirror_url_template='/apk/%d7%a8%d7%a9%d7%aa-13/'
                               '%d7%a8%d7%a9%d7%aa-13-%d7%a6%d7%a4%d7%99%d7%99%d7%94-%d7%91%d7%9b%d7%9c-%d7%aa%d7%95%d7%9b%d7%a0%d7%99%d7%95%d7%aa-%d7%a8%d7%a9%d7%aa/'
                               '%d7%a8%d7%a9%d7%aa-13-%d7%a6%d7%a4%d7%99%d7%99%d7%94-%d7%91%d7%9b%d7%9c-%d7%aa%d7%95%d7%9b%d7%a0%d7%99%d7%95%d7%aa-%d7%a8%d7%a9%d7%aa-{}-release/',
        patcher_name='ReshetPatcher',
    ),
    AppConfig(
        name='OkCupid',
        package_name='com.okcupid.okcupid',
        patcher_name='OkCupidPatcher',
    ),
]
