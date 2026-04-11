"""Tenant API views."""
from django.db import models
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Tenant, TenantDocument
from .serializers import (
    DocumentUploadSerializer,
    MoveOutSerializer,
    TenantCreateSerializer,
    TenantDetailSerializer,
    TenantDocumentSerializer,
    TenantListSerializer,
)
from .services import FileValidationError, move_in_tenant, move_out_tenant, validate_upload


class TenantViewSet(viewsets.ModelViewSet):
    """
    CRUD for tenants.
    List → TenantListSerializer (compact).
    Retrieve → TenantDetailSerializer (full + documents).
    Create triggers move-in workflow.
    """

    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = Tenant.objects.select_related("unit", "unit__building").order_by("-move_in_date")

        # Filters
        tenant_status = self.request.query_params.get("status")
        if tenant_status:
            qs = qs.filter(status=tenant_status)

        building_id = self.request.query_params.get("building")
        if building_id:
            qs = qs.filter(unit__building_id=building_id)

        unit_id = self.request.query_params.get("unit")
        if unit_id:
            qs = qs.filter(unit_id=unit_id)

        search = self.request.query_params.get("search")
        if search:
            qs = qs.filter(
                models.Q(first_name__icontains=search)
                | models.Q(last_name__icontains=search)
                | models.Q(id_number__icontains=search)
                | models.Q(phone__icontains=search)
            )

        return qs

    def get_serializer_class(self):
        if self.action == "retrieve":
            return TenantDetailSerializer
        if self.action == "create":
            return TenantCreateSerializer
        return TenantListSerializer

    def perform_create(self, serializer):
        tenant = serializer.save()
        move_in_tenant(tenant)

    @action(detail=True, methods=["post"], url_path="move-out")
    def move_out(self, request, pk=None):
        """POST /api/tenants/<id>/move-out/"""
        tenant = self.get_object()
        if not tenant.is_active:
            return Response(
                {"detail": "Tenant is not active."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        serializer = MoveOutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        move_out_tenant(
            tenant,
            move_out_date=serializer.validated_data.get("move_out_date"),
            notes=serializer.validated_data.get("notes", ""),
        )
        return Response(TenantDetailSerializer(tenant).data, status=status.HTTP_200_OK)

    @action(
        detail=True,
        methods=["post"],
        url_path="documents",
        parser_classes=[MultiPartParser, FormParser],
    )
    def upload_document(self, request, pk=None):
        """POST /api/tenants/<id>/documents/ (multipart form)."""
        tenant = self.get_object()
        serializer = DocumentUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        uploaded_file = serializer.validated_data["file"]
        try:
            validate_upload(uploaded_file)
        except FileValidationError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        doc = TenantDocument.objects.create(
            tenant=tenant,
            doc_type=serializer.validated_data["doc_type"],
            file=uploaded_file,
            original_name=uploaded_file.name,
        )
        return Response(
            TenantDocumentSerializer(doc).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["get"], url_path="documents/list")
    def list_documents(self, request, pk=None):
        """GET /api/tenants/<id>/documents/list/"""
        tenant = self.get_object()
        docs = tenant.documents.all()
        return Response(TenantDocumentSerializer(docs, many=True).data)
