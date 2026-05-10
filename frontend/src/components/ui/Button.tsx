import React from 'react';
import { cn } from './cn';

type Variant = 'primary' | 'ghost' | 'danger';
type Size = 'sm' | 'md' | 'icon';

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
}

const variantClasses: Record<Variant, string> = {
  primary:
    'bg-accent/80 text-white hover:bg-accent border border-accent/60',
  ghost:
    'bg-surface text-fg-secondary hover:bg-surface-hover hover:text-fg border border-border',
  danger:
    'text-danger hover:bg-danger/10 hover:border-danger/50 border border-transparent',
};

const sizeClasses: Record<Size, string> = {
  sm: 'px-2 py-1 text-xs rounded',
  md: 'px-3 py-1.5 text-sm rounded-md',
  icon: 'p-1.5 rounded',
};

export const Button: React.FC<ButtonProps> = ({
  variant = 'ghost',
  size = 'md',
  className,
  children,
  ...props
}) => {
  return (
    <button
      type="button"
      className={cn(
        'inline-flex items-center justify-center gap-1.5 font-medium transition-colors',
        variantClasses[variant],
        sizeClasses[size],
        className
      )}
      {...props}
    >
      {children}
    </button>
  );
};
