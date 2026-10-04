"use client";

import { useDashboard } from "@/components/AppShell";
import AddBusinessForm from "@/components/AddBusinessForm";
import BusinessTable from "@/components/BusinessTable";

export default function BusinessesPage() {
  const {
    businesses,
    busyId,
    addBusiness,
    enqueueOne,
    enqueueAll,
    removeBusiness,
    updateBusiness,
  } = useDashboard();

  return (
    <>
      <div className="page-head">
        <h2>Businesses</h2>
        <span className="section-hint">
          add a listing, edit its name or Maps link (renaming pulls in matching CSV rows), or
          rescan it
        </span>
      </div>
      <AddBusinessForm onAdd={addBusiness} />
      <BusinessTable
        businesses={businesses}
        busyId={busyId}
        onEnqueue={enqueueOne}
        onEnqueueAll={enqueueAll}
        onDelete={removeBusiness}
        onUpdate={updateBusiness}
      />
    </>
  );
}
