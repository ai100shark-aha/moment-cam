from django.contrib import admin

from .models import AppSettings, Photo, RaceSession


@admin.register(Photo)
class PhotoAdmin(admin.ModelAdmin):
    list_display = ("taken_at", "mode", "status", "target", "caption", "people_count")
    list_filter = ("mode", "status", "target")
    date_hierarchy = "taken_at"


admin.site.register(RaceSession)
admin.site.register(AppSettings)
