import React from 'react';
import { type LucideIcon } from 'lucide-react';
import { cn } from './cn';

interface IconButtonProps {
  icon: LucideIcon;
  label: string;
  active?: boolean;
  onClick: () => void;
  className?: string;
  size?: 'sm' | 'md';
}

const sizeClasses = {
  sm: 'w-6 h-6',
  md: 'w-8 h-8',
};

const iconSizeClasses = {
  sm: 'w-3.5 h-3.5',
  md: 'w-4 h-4',
};

export const IconButton: React.FC<IconButtonProps> = ({
  icon: Icon,
  label,
  active = false,
  onClick,
  className,
  size = 'md',
}) => {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        sizeClasses[size],
        'rounded flex items-center justify-center transition-colors',
        active
          ? 'text-fg bg-surface-hover'
          : 'text-fg-secondary hover:text-fg hover:bg-surface-hover',
        className
      )}
      title={label}
      aria-label={label}
    >
      <Icon className={iconSizeClasses[size]} />
    </button>
  );
};
