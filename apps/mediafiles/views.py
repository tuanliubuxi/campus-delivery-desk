"""Authenticated local-media download endpoint."""

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404

from .models import MediaFile
from .services import media_absolute_path


@login_required
def download_media(request, media_id):
    media = get_object_or_404(MediaFile, pk=media_id, deleted_at__isnull=True)
    if request.user.is_courier:
        owns_evidence = media.delivery_evidence.filter(drop__courier=request.user).exists()
        owns_annotation = media.annotation_evidence.filter(drop__courier=request.user).exists()
        owns_exception = media.exception_attachments.filter(
            exception_case__created_by=request.user
        ).exists()
        if not (owns_evidence or owns_annotation or owns_exception):
            raise PermissionDenied("不能访问其他配送员的媒体")
    path = media_absolute_path(media)
    if not path.is_file():
        raise Http404("媒体文件不存在")
    return FileResponse(path.open("rb"), content_type=media.mime_type)
