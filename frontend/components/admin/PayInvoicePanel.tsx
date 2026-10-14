"use client";

import { useState, type FormEvent } from "react";

import { Card } from "@/components/ui/Card";
import { Button, Message, SelectField, TextField, useAction } from "@/components/ui/Form";
import { apiPost } from "@/lib/api";
import { formatMoney } from "@/lib/format";
import type { InvoiceRow } from "@/lib/types";

const METHODS = [
  { value: "bank_transfer", label: "Bank transfer" },
  { value: "jazzcash", label: "JazzCash" },
  { value: "easypaisa", label: "Easypaisa" },
  { value: "card", label: "Card" },
  { value: "other", label: "Other" },
];

/** "Mark as paid": records a payment for an invoice (the whole balance, or part of it). */
export function PayInvoicePanel({ invoice, onDone, onCancel }: { invoice: InvoiceRow; onDone: () => void; onCancel: () => void }) {
  const [method, setMethod] = useState("bank_transfer");
  const [amount, setAmount] = useState(String(invoice.balance));
  const [reference, setReference] = useState("");
  const [paidOn, setPaidOn] = useState(new Date().toISOString().slice(0, 10));

  const pay = useAction(async () => {
    await apiPost(`/api/admin/invoices/${invoice.id}/payments`, {
      method,
      amount: Number(amount),
      reference: reference || null,
      paid_on: paidOn || null,
    });
    onDone();
  });

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    pay.run();
  }

  return (
    <Card className="p-4 sm:p-5">
      <h3 className="text-sm font-semibold text-ink">
        Record a payment for {invoice.number}
        {invoice.client_name ? ` · ${invoice.client_name}` : ""}
      </h3>
      <p className="mt-0.5 text-xs text-muted">Still owed: {formatMoney(invoice.balance, invoice.currency)}. Paying the full amount marks the invoice as paid (and lifts a suspension).</p>
      <form onSubmit={onSubmit} className="mt-4 grid gap-4 sm:grid-cols-4">
        <SelectField label="Paid by" value={method} onChange={(e) => setMethod(e.target.value)}>
          {METHODS.map((m) => (
            <option key={m.value} value={m.value}>
              {m.label}
            </option>
          ))}
        </SelectField>
        <TextField label={`Amount (${invoice.currency})`} required type="number" min="0.01" step="0.01" value={amount} onChange={(e) => setAmount(e.target.value)} />
        <TextField label="Reference" value={reference} onChange={(e) => setReference(e.target.value)} placeholder="Transaction ID / receipt" />
        <TextField label="Received on" type="date" value={paidOn} onChange={(e) => setPaidOn(e.target.value)} />
        <div className="flex flex-wrap items-center gap-3 sm:col-span-4">
          <Button type="submit" variant="primary" busy={pay.busy}>
            Record payment
          </Button>
          <Button variant="ghost" onClick={onCancel}>
            Cancel
          </Button>
        </div>
        {pay.error && (
          <div className="sm:col-span-4">
            <Message kind="error">{pay.error}</Message>
          </div>
        )}
      </form>
    </Card>
  );
}
