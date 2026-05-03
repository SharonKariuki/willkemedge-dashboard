
// ─── Tenant Detail Modal ─────────────────────────────────────────────────────
function TenantDetailModal({ tenantId, onClose }: { tenantId: number; onClose: () => void }) {
  const { data: tenant, isLoading } = useTenant(tenantId);
  const updateTenant = useUpdateTenant(tenantId);
  const moveOutNotice = useMoveOutNotice(tenantId);
  const moveOut = useMoveOutTenant(tenantId);

  const [mode, setMode] = useState<"view" | "edit" | "notice" | "moveout">("view");

  const editForm = useForm({
    defaultValues: {
      first_name: tenant?.first_name ?? "",
      last_name: tenant?.last_name ?? "",
      phone: tenant?.phone ?? "",
      email: tenant?.email ?? "",
      monthly_rent: String(tenant?.monthly_rent ?? ""),
      deposit_paid: String(tenant?.deposit_paid ?? ""),
      deposit_refund_percentage: String(tenant?.deposit_refund_percentage ?? "100"),
      emergency_contact: tenant?.emergency_contact ?? "",
      emergency_phone: tenant?.emergency_phone ?? "",
      notes: tenant?.notes ?? "",
    },
  });

  const noticeForm = useForm({
    defaultValues: {
      notice_date: new Date().toISOString().slice(0, 10),
      intended_move_out_date: "",
      notes: "",
    },
  });

  const moveOutForm = useForm({
    defaultValues: {
      move_out_date: new Date().toISOString().slice(0, 10),
      deposit_refund_percentage: "100",
      notes: "",
    },
  });

  // Reset edit form when tenant data loads
  useEffect(() => {
    if (tenant) {
      editForm.reset({
        first_name: tenant.first_name,
        last_name: tenant.last_name,
        phone: tenant.phone,
        email: tenant.email ?? "",
        monthly_rent: String(tenant.monthly_rent),
        deposit_paid: String(tenant.deposit_paid),
        deposit_refund_percentage: String(tenant.deposit_refund_percentage ?? "100"),
        emergency_contact: tenant.emergency_contact ?? "",
        emergency_phone: tenant.emergency_phone ?? "",
        notes: tenant.notes ?? "",
      });
    }
  }, [tenant]);

  const handleEdit = async (values: Record<string, unknown>) => {
    try {
      await updateTenant.mutateAsync(values);
      toast.success("Tenant updated");
      setMode("view");
    } catch { toast.error("Failed to update tenant"); }
  };

  const handleNotice = async (values: Record<string, string>) => {
    try {
      await moveOutNotice.mutateAsync(values as { notice_date: string; intended_move_out_date: string; notes?: string });
      toast.success("Move-out notice recorded");
      setMode("view");
    } catch { toast.error("Failed to record notice"); }
  };

  const handleMoveOut = async (values: Record<string, string>) => {
    try {
      await moveOut.mutateAsync({
        move_out_date: values.move_out_date,
        notes: values.notes,
        deposit_refund_percentage: Number(values.deposit_refund_percentage),
      });
      toast.success("Tenant moved out");
      onClose();
    } catch { toast.error("Failed to process move-out"); }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-ink-900/40 backdrop-blur-sm" onClick={onClose} />
      <div className="relative w-full max-w-2xl max-h-[90vh] overflow-y-auto rounded-xl bg-white shadow-float dark:bg-ink-900 animate-fade-up">
        {/* Header */}
        <div className="sticky top-0 z-10 flex items-center justify-between border-b border-ink-100 bg-white px-6 py-4 dark:border-ink-700 dark:bg-ink-900">
          <p className="font-display text-lg font-semibold text-ink-900 dark:text-white">
            {isLoading ? "Loading…" : tenant?.full_name}
          </p>
          <div className="flex items-center gap-2">
            {tenant?.is_active && mode === "view" && (
              <>
                <Button size="sm" variant="glass" onClick={() => setMode("edit")}>
                  <Pencil className="h-3.5 w-3.5" /> Edit
                </Button>
                <Button size="sm" variant="glass" onClick={() => setMode("notice")}>
                  <AlertTriangle className="h-3.5 w-3.5" /> Notice
                </Button>
                <Button size="sm" variant="danger" onClick={() => setMode("moveout")}>
                  <LogOut className="h-3.5 w-3.5" /> Move Out
                </Button>
              </>
            )}
            {mode !== "view" && (
              <Button size="sm" variant="ghost" onClick={() => setMode("view")}>Cancel</Button>
            )}
            <button onClick={onClose} className="rounded-md p-1.5 text-ink-400 hover:text-ink-700">
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>

        <div className="p-6 space-y-5">
          {isLoading && <div className="space-y-3">{Array.from({length:4}).map((_,i) => <div key={i} className="h-8 rounded bg-ink-100 animate-pulse" />)}</div>}

          {tenant && mode === "view" && (
            <>
              {/* Profile header */}
              <div className="flex items-center gap-4">
                <img src={avatarFor(tenant.full_name)} alt="" className="h-14 w-14 rounded-full shadow" />
                <div>
                  <p className="font-display text-xl font-semibold text-ink-900">{tenant.full_name}</p>
                  <p className="text-sm text-ink-500">{tenant.building_name} — {tenant.unit_label}</p>
                  <Badge tone={tenant.status === "active" ? "sage" : tenant.status === "notice_given" ? "ochre" : "neutral"} withDot className="mt-1">
                    {tenant.status_display}
                  </Badge>
                </div>
              </div>

              {/* Info grid */}
              <div className="grid gap-2 sm:grid-cols-2 text-sm">
                {[
                  ["Phone", tenant.phone],
                  ["Email", tenant.email || "—"],
                  ["ID Number", tenant.id_number],
                  ["Emergency Contact", tenant.emergency_contact || "—"],
                  ["Move-in Date", tenant.move_in_date],
                  ["Move-out Date", tenant.move_out_date || "—"],
                  ["Monthly Rent", `KES ${Number(tenant.monthly_rent).toLocaleString()}`],
                  ["Deposit Paid", `KES ${Number(tenant.deposit_paid).toLocaleString()}`],
                  ["Deposit Refund %", `${tenant.deposit_refund_percentage ?? 100}%`],
                  ...(tenant.deposit_refund_amount != null ? [["Deposit Refund", `KES ${Number(tenant.deposit_refund_amount).toLocaleString()}`]] : []),
                  ...(tenant.notice_date ? [["Notice Given", tenant.notice_date]] : []),
                  ...(tenant.intended_move_out_date ? [["Intended Move-out", tenant.intended_move_out_date]] : []),
                ].map(([k, v]) => (
                  <div key={k} className="flex justify-between gap-2 rounded-md bg-ink-50 px-3 py-2 dark:bg-ink-800">
                    <span className="text-ink-500">{k}</span>
                    <span className="font-medium text-ink-900 dark:text-white">{v}</span>
                  </div>
                ))}
              </div>

              {/* Payment analytics */}
              <div className="rounded-md bg-sage-500/8 p-4 space-y-1">
                <p className="text-[11px] font-medium uppercase tracking-wider text-ink-500">Payment Analytics</p>
                <div className="grid grid-cols-2 gap-3 mt-2">
                  <div className="rounded-md bg-white p-3 text-center dark:bg-ink-800">
                    <p className="font-display text-xl font-semibold text-sage-700">KES {(tenant.total_paid ?? 0).toLocaleString()}</p>
                    <p className="text-[11px] text-ink-500">Total paid</p>
                  </div>
                  <div className="rounded-md bg-white p-3 text-center dark:bg-ink-800">
                    <p className={`font-display text-xl font-semibold ${(tenant.total_arrears ?? 0) > 0 ? "text-status-unpaid" : "text-sage-700"}`}>
                      KES {(tenant.total_arrears ?? 0).toLocaleString()}
                    </p>
                    <p className="text-[11px] text-ink-500">Outstanding arrears</p>
                  </div>
                </div>
              </div>
            </>
          )}

          {/* Edit form */}
          {tenant && mode === "edit" && (
            <form onSubmit={editForm.handleSubmit(handleEdit)} className="space-y-4">
              <p className="font-medium text-ink-900">Edit Tenant Details</p>
              <div className="grid gap-3 sm:grid-cols-2">
                <Field label="First name"><input {...editForm.register("first_name")} className={inputCls} /></Field>
                <Field label="Last name"><input {...editForm.register("last_name")} className={inputCls} /></Field>
                <Field label="Phone"><input {...editForm.register("phone")} className={inputCls} /></Field>
                <Field label="Email"><input {...editForm.register("email")} className={inputCls} /></Field>
                <Field label="Monthly rent (KES)"><input {...editForm.register("monthly_rent")} className={inputCls} /></Field>
                <Field label="Deposit paid (KES)"><input {...editForm.register("deposit_paid")} className={inputCls} /></Field>
                <Field label="Emergency contact"><input {...editForm.register("emergency_contact")} className={inputCls} /></Field>
                <Field label="Emergency phone"><input {...editForm.register("emergency_phone")} className={inputCls} /></Field>
              </div>
              <div className="flex justify-end gap-2">
                <Button type="button" variant="ghost" onClick={() => setMode("view")}>Cancel</Button>
                <Button type="submit" loading={updateTenant.isPending}>Save changes</Button>
              </div>
            </form>
          )}

          {/* Move-out notice form */}
          {tenant && mode === "notice" && (
            <form onSubmit={noticeForm.handleSubmit(handleNotice)} className="space-y-4">
              <p className="font-medium text-ink-900">Record Move-out Notice</p>
              <div className="grid gap-3 sm:grid-cols-2">
                <DatePicker label="Notice date" {...noticeForm.register("notice_date")} />
                <DatePicker label="Intended move-out date" {...noticeForm.register("intended_move_out_date")} />
              </div>
              <Field label="Notes"><textarea {...noticeForm.register("notes")} rows={2} className={inputCls} /></Field>
              <div className="flex justify-end gap-2">
                <Button type="button" variant="ghost" onClick={() => setMode("view")}>Cancel</Button>
                <Button type="submit" loading={moveOutNotice.isPending}>Record notice</Button>
              </div>
            </form>
          )}

          {/* Move-out form */}
          {tenant && mode === "moveout" && (
            <form onSubmit={moveOutForm.handleSubmit(handleMoveOut)} className="space-y-4">
              <div className="rounded-md bg-status-unpaid/8 p-3 text-sm text-status-unpaid flex items-center gap-2">
                <AlertTriangle className="h-4 w-4 shrink-0" />
                This action will move the tenant out and free up the unit.
              </div>
              <DatePicker label="Move-out date" {...moveOutForm.register("move_out_date")} />
              <Field label="Deposit refund %">
                <input type="number" min={0} max={100} step={1} {...moveOutForm.register("deposit_refund_percentage")} className={inputCls} />
                <p className="mt-1 text-[11px] text-ink-500">
                  Deposit paid: KES {Number(tenant.deposit_paid).toLocaleString()}.
                  Refund at 100%: KES {Number(tenant.deposit_paid).toLocaleString()}.
                  Reduce if there are damages.
                </p>
              </Field>
              <Field label="Move-out notes"><textarea {...moveOutForm.register("notes")} rows={2} className={inputCls} /></Field>
              <div className="flex justify-end gap-2">
                <Button type="button" variant="ghost" onClick={() => setMode("view")}>Cancel</Button>
                <Button type="submit" variant="danger" loading={moveOut.isPending}>
                  <LogOut className="h-4 w-4" /> Confirm move-out
                </Button>
              </div>
            </form>
          )}
        </div>
      </div>
    </div>
  );
}
