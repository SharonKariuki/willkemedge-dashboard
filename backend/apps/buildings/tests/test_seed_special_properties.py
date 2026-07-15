"""Tests for the seed_special_properties command (farms + Baobab Karen)."""
from io import StringIO

import pytest
from django.core.management import call_command

from apps.buildings.models import Building, PropertyType


def _run(*args):
    out = StringIO()
    call_command("seed_special_properties", *args, stdout=out)
    return out.getvalue()


@pytest.mark.django_db
class TestSeedSpecialProperties:
    def test_creates_farms_and_karen(self):
        _run()
        assert Building.objects.get(code="FS").property_type == PropertyType.FARM
        assert Building.objects.get(code="FMN").property_type == PropertyType.FARM
        assert Building.objects.get(code="FNN").property_type == PropertyType.FARM
        karen = Building.objects.get(code="KN")
        assert karen.property_type == PropertyType.EXPENSE_ONLY

    def test_karen_is_income_disabled(self):
        _run()
        assert Building.objects.get(code="FS").allows_income is True
        assert Building.objects.get(code="KN").allows_income is False

    def test_is_idempotent(self):
        _run()
        out = _run()
        assert "0 created, 0 updated" in out
        assert Building.objects.filter(code__in=["FS", "FMN", "FNN", "KN"]).count() == 4

    def test_dry_run_writes_nothing(self):
        out = _run("--dry-run")
        assert "DRY RUN" in out
        assert not Building.objects.filter(code="FS").exists()
