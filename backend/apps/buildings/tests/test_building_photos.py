"""Building cover photos: stored in the database, type checked by content."""
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from apps.accounts.models import AuditLog, User
from apps.buildings.models import Building
from apps.buildings.photos import MAX_PHOTO_BYTES, sniff_image_type

pytestmark = pytest.mark.django_db

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
WEBP = b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"\x00" * 64


@pytest.fixture
def client():
    user = User.objects.create_user(username="osoro", email="osoro@test.com", password="pass12345!", role="owner")
    c = APIClient()
    c.force_authenticate(user=user)
    return c


@pytest.fixture
def building():
    return Building.objects.create(name="Donholm", code="DON")


def _upload(data, name="photo.jpg", content_type="image/jpeg"):
    return SimpleUploadedFile(name, data, content_type=content_type)


@pytest.mark.parametrize("data,expected", [
    (JPEG, "image/jpeg"), (PNG, "image/png"), (WEBP, "image/webp"),
    (b"<script>alert(1)</script>", None), (b"GIF89a", None), (b"", None),
])
def test_type_comes_from_the_bytes(data, expected):
    assert sniff_image_type(data) == expected


def test_no_photo_means_placeholder(client, building):
    listed = client.get("/api/buildings/").data[0]
    assert listed["has_photo"] is False
    assert client.get(f"/api/buildings/{building.pk}/photo/").status_code == 404


def test_upload_then_serve(client, building):
    resp = client.put(f"/api/buildings/{building.pk}/photo/", {"photo": _upload(PNG, "front.png")}, format="multipart")
    assert resp.status_code == 200, resp.data
    assert resp.data["has_photo"] is True
    assert resp.data["photo_version"]

    served = client.get(f"/api/buildings/{building.pk}/photo/")
    assert served.status_code == 200
    assert served["Content-Type"] == "image/png"
    assert served.content == PNG


def test_rejects_a_file_that_only_claims_to_be_an_image(client, building):
    fake = _upload(b"<html>not an image</html>", "evil.jpg", "image/jpeg")
    resp = client.put(f"/api/buildings/{building.pk}/photo/", {"photo": fake}, format="multipart")
    assert resp.status_code == 400
    building.refresh_from_db()
    assert building.photo_content_type == ""


def test_rejects_an_oversized_photo(client, building):
    big = _upload(JPEG + b"\x00" * MAX_PHOTO_BYTES)
    resp = client.put(f"/api/buildings/{building.pk}/photo/", {"photo": big}, format="multipart")
    assert resp.status_code == 400
    assert "too large" in resp.data["detail"]


def test_remove_falls_back_to_placeholder(client, building):
    client.put(f"/api/buildings/{building.pk}/photo/", {"photo": _upload(JPEG)}, format="multipart")
    assert client.delete(f"/api/buildings/{building.pk}/photo/").status_code == 204
    assert client.get(f"/api/buildings/{building.pk}/photo/").status_code == 404
    assert client.get(f"/api/buildings/{building.pk}/").data["has_photo"] is False


def test_photo_needs_a_login(building):
    assert APIClient().get(f"/api/buildings/{building.pk}/photo/").status_code == 401


def test_audit_log_notes_the_photo_change_without_the_image(client, building):
    client.put(f"/api/buildings/{building.pk}/photo/", {"photo": _upload(PNG)}, format="multipart")
    rows = AuditLog.objects.filter(object_type="building", object_id=building.pk)
    photo_rows = [r for r in rows if "photo" in r.new_values]
    assert photo_rows, "the photo change should be on the building's history"
    for r in photo_rows:
        assert r.new_values["photo"] == "(hidden)"
        assert "PNG" not in str(r.new_values) and "PNG" not in str(r.old_values)
        assert "photo_updated_at" not in r.new_values
