/**
 * Shared TypeScript types mirroring backend API shapes.
 */

export type UnitStatus =
  | "vacant"
  | "occupied_paid"
  | "occupied_partial"
  | "occupied_unpaid"
  | "arrears";

export type UnitType =
  | "single"
  | "double"
  | "bedsitter"
  | "1br"
  | "2br"
  | "3br"
  | "shop";

export interface Unit {
  id: number;
  building: number;
  building_name: string;
  label: string;
  floor: number;
  unit_type: UnitType;
  monthly_rent: string;
  status: UnitStatus;
  status_display: string;
  notes: string;
  created_at: string;
  updated_at: string;
}

export interface Building {
  id: number;
  name: string;
  address: string;
  total_floors: number;
  notes: string;
  unit_count: number;
  occupied_count: number;
  created_at: string;
  updated_at: string;
}

export interface BuildingDetail extends Building {
  units: Unit[];
}

export interface UnitStatusSummary {
  total: number;
  vacant: number;
  occupied_paid: number;
  occupied_partial: number;
  occupied_unpaid: number;
  arrears: number;
}

// --- Tenants ---

export type TenantStatus = "active" | "moved_out" | "archived";

export type DocumentType = "id_front" | "id_back" | "passport" | "lease" | "other";

export interface TenantDocument {
  id: number;
  tenant: number;
  doc_type: DocumentType;
  doc_type_display: string;
  file: string;
  original_name: string;
  uploaded_at: string;
}

export interface TenantListItem {
  id: number;
  full_name: string;
  first_name: string;
  last_name: string;
  phone: string;
  unit: number;
  unit_label: string;
  building_name: string;
  monthly_rent: string;
  status: TenantStatus;
  status_display: string;
  move_in_date: string;
  move_out_date: string | null;
}

export interface TenantDetail extends TenantListItem {
  id_number: string;
  email: string;
  emergency_contact: string;
  emergency_phone: string;
  deposit_paid: string;
  move_out_notes: string;
  notes: string;
  documents: TenantDocument[];
  created_at: string;
  updated_at: string;
}
