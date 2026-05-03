"""Dashboard views_reports — all reporting endpoints."""
from collections import defaultdict
from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.buildings.models import Building, Unit, UnitStatus
from apps.expenses.models import Expense
from apps.payments.models import Arrears, Payment
from apps.tenants.models import Tenant, TenantStatus

