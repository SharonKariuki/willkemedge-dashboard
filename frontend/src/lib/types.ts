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
  monthly_rent: string; // decimal from DRF
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
