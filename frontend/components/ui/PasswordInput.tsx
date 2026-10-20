"use client";

import { useRef, useState, type InputHTMLAttributes } from "react";

import { Icon } from "@/components/layout/icons";

type Props = Omit<InputHTMLAttributes<HTMLInputElement>, "type"> & {
  /** Is the password shown as plain text? Leave it out and the box remembers this by itself. */
  shown?: boolean;
  onShownChange?: (shown: boolean) => void;
};

/**
 * A password box with an eye button at the end that shows or hides what is typed.
 * Every password field uses it (login, reset, account, admin). Everything else works like a normal <input>.
 * Inside a <label> the box comes before the eye button, so clicking the label text still focuses the box.
 */
export function PasswordInput({ shown, onShownChange, className = "", ...input }: Props) {
  const [own, setOwn] = useState(false);
  const visible = shown ?? own;
  const box = useRef<HTMLInputElement>(null);

  function toggle() {
    const next = !visible;
    setOwn(next);
    onShownChange?.(next);
    box.current?.focus(); // so the person can keep typing right away
  }

  const label = visible ? "Hide password" : "Show password";
  return (
    <span className="relative block">
      {/* pr-10 leaves room for the eye, so long passwords never run under it */}
      <input {...input} ref={box} type={visible ? "text" : "password"} className={`${className} pr-10`} />
      <button
        type="button"
        onClick={toggle}
        aria-label={label}
        title={label}
        className="absolute inset-y-0 right-0 grid w-10 place-items-center rounded-r-lg text-muted hover:text-ink"
      >
        <Icon name={visible ? "eyeOff" : "eye"} />
      </button>
    </span>
  );
}
