from django.urls import path

from . import views

urlpatterns = [
    path("", views.camera_view, name="camera"),
    path("today/", views.today_view, name="today"),
    path("settings/", views.settings_view, name="settings"),
    path("manifest.webmanifest", views.manifest, name="manifest"),
    path("sw.js", views.service_worker, name="sw"),
    path("offline/", views.offline, name="offline"),
    path("api/state/", views.api_state, name="api_state"),
    path("api/photos/", views.api_upload, name="api_upload"),
    path("api/photos/<int:pk>/publish/", views.api_publish, name="api_publish"),
    path("api/photos/<int:pk>/cancel/", views.api_cancel, name="api_cancel"),
    path("api/bundle/", views.api_bundle, name="api_bundle"),
    path("api/race/start/", views.api_race_start, name="api_race_start"),
    path("api/race/finish/", views.api_race_finish, name="api_race_finish"),
]
