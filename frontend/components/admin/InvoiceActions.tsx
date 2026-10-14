"use client";

import { Button, Message, useAction } from "@/components/ui/Form";
import { apiPost } from "@/lib/api";
import type { InvoiceRow } from "@/lib/types";

/** The admin's buttons on an invoice row: Mark as paid, Email, Cancel. */
export function InvoiceActions({ invoice, onPay, onChanged }: { invoice: InvoiceRow; onPay: (invoice: InvoiceRow) => void; onChanged: () => void }) {
  const send = useAction(async () => {
    const result = await apiPost<{ sent: boolean; to: string[] }>(`/api/admin/invoices/${invoice.id}/send`);
    window.alert(result.sent ? `Sent to ${result.to.join(", ")}` : "The email could not be sent. See the server log.");
    onChanged();
  });
  const cancel = useAction(async () => {
    if (!window.confirm(`Cancel invoice ${invoice.number}? This can't be undone.`)) return;
    await apiPost(`/api/admin/invoices/${invoice.id}/void`);
    onChanged();
  });

  if (invoice.status !== "open") return null;
  return (
    <>
      <Button variant="primary" className="!px-2.5 !py-1 text-xs" onClick={() => onPay(invoice)}>
        Mark as paid
      </Button>
      <Button variant="ghost" className="!px-2.5 !py-1 text-xs" busy={send.busy} onClick={() => send.run()}>
        Email
      </Button>
      <Button variant="ghost" className="!px-2.5 !py-1 text-xs !text-bad" busy={cancel.busy} onClick={() => cancel.run()}>
        Cancel
      </Button>
      {(send.error || cancel.error) && (
        <div className="basis-full text-left">
          <Message kind="error">{send.error ?? cancel.error}</Message>
        </div>
      )}
    </>
  );
}
