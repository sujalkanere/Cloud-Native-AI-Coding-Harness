import * as React from "react";
import { cn } from "../../lib/utils";

export interface BadgeProps extends React.HTMLAttributes<HTMLDivElement> {
  variant?:
    | "default"
    | "secondary"
    | "destructive"
    | "outline"
    | "success"
    | "warning"
    | "info";
}

function Badge({
  className,
  variant = "default",
  ...props
}: BadgeProps) {
  const variantStyles = {
    default:
      "border-transparent bg-blue-600 text-white shadow hover:bg-blue-700",
    secondary:
      "border-transparent bg-slate-800 text-slate-200 hover:bg-slate-700",
    destructive:
      "border-transparent bg-rose-900/80 text-rose-200 border border-rose-700",
    outline: "text-slate-300 border border-slate-700",
    success:
      "border-transparent bg-emerald-950/80 text-emerald-300 border border-emerald-800",
    warning:
      "border-transparent bg-amber-950/80 text-amber-300 border border-amber-800",
    info:
      "border-transparent bg-sky-950/80 text-sky-300 border border-sky-800",
  };

  return (
    <div
      className={cn(
        "inline-flex items-center rounded-md border px-2.5 py-0.5 text-xs font-semibold transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500",
        variantStyles[variant],
        className
      )}
      {...props}
    />
  );
}

export { Badge };
