"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { Button, Message, TextArea, TextField, useAction } from "@/components/ui/Form";
import { Card } from "@/components/ui/Card";
import { PageHeader } from "@/components/ui/PageHeader";
import { apiPost } from "@/lib/api";
import type { AdminClient } from "@/lib/types";

export default function NewClientPage() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [notes, setNotes] = useState("");

  const create = useAction(async () => {
    const client = await apiPost<AdminClient>("/api/admin/clients", { name, contact_email: email || null, phone: phone || null, notes: notes || null });
    router.push(`/admin/clients/${client.id}`); // next: add their website
  });

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    create.run();
  }

  return (
    <>
      <Link href="/admin/clients" className="mb-3 inline-block text-sm text-accent hover:underline">
        ← All clients
      </Link>
      <PageHeader title="New client" description="Next you'll add their website and invite their people." />
      <Card className="max-w-xl p-5">
        <form onSubmit={onSubmit} className="space-y-4">
          {create.error && <Message kind="error">{create.error}</Message>}
          <TextField label="Business name" required value={name} onChange={(e) => setName(e.target.value)} maxLength={200} />
          <TextField label="Contact email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} hint="Where invoices and reports are addressed." />
          <TextField label="Phone / WhatsApp" value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="+92 300 1234567" />
          <TextArea label="Private notes" value={notes} onChange={(e) => setNotes(e.target.value)} hint="Only you can see these." />
          <Button type="submit" variant="primary" busy={create.busy}>
            Create client
          </Button>
        </form>
      </Card>
    </>
  );
}
