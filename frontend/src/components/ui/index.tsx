import * as React from "react";
import * as SwitchPrimitive from "@radix-ui/react-switch";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
export function Button({
  className,
  variant = "default",
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "default" | "secondary" | "ghost" | "danger";
}) {
  return (
    <button className={cn("btn", `btn-${variant}`, className)} {...props} />
  );
}
export function Switch(
  props: React.ComponentPropsWithoutRef<typeof SwitchPrimitive.Root>,
) {
  return (
    <SwitchPrimitive.Root className="switch" {...props}>
      <SwitchPrimitive.Thumb className="switch-thumb" />
    </SwitchPrimitive.Root>
  );
}
export function Modal({
  open,
  onOpenChange,
  title,
  description,
  children,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: string;
  children: React.ReactNode;
}) {
  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="modal-overlay" />
        <DialogPrimitive.Content className="modal-content">
          <DialogPrimitive.Title className="modal-title">
            {title}
          </DialogPrimitive.Title>
          <DialogPrimitive.Description className="muted modal-description">
            {description}
          </DialogPrimitive.Description>
          <DialogPrimitive.Close
            className="icon-btn modal-close"
            aria-label="Закрыть"
          >
            <X size={18} />
          </DialogPrimitive.Close>
          {children}
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}
