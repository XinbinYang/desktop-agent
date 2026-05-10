import React from 'react';
import * as DropdownMenuPrimitive from '@radix-ui/react-dropdown-menu';
import { cn } from './cn';

export const DropdownMenu = DropdownMenuPrimitive.Root;
export const DropdownMenuTrigger = DropdownMenuPrimitive.Trigger;

interface ContentProps extends DropdownMenuPrimitive.DropdownMenuContentProps {
  align?: 'start' | 'center' | 'end';
}

export const DropdownMenuContent: React.FC<ContentProps> = ({
  className,
  align = 'end',
  sideOffset = 4,
  children,
  ...props
}) => (
  <DropdownMenuPrimitive.Portal>
    <DropdownMenuPrimitive.Content
      align={align}
      sideOffset={sideOffset}
      className={cn(
        'z-50 min-w-[140px] bg-surface-elevated border border-border rounded-md shadow-lg py-1',
        className
      )}
      {...props}
    >
      {children}
    </DropdownMenuPrimitive.Content>
  </DropdownMenuPrimitive.Portal>
);

interface ItemProps extends DropdownMenuPrimitive.DropdownMenuItemProps {
  destructive?: boolean;
}

export const DropdownMenuItem: React.FC<ItemProps> = ({
  className,
  destructive,
  children,
  ...props
}) => (
  <DropdownMenuPrimitive.Item
    className={cn(
      'flex items-center gap-2 px-3 py-1.5 text-xs cursor-pointer outline-none select-none',
      destructive
        ? 'text-danger data-[highlighted]:bg-danger/10'
        : 'text-fg-secondary data-[highlighted]:bg-surface-hover data-[highlighted]:text-fg',
      className
    )}
    {...props}
  >
    {children}
  </DropdownMenuPrimitive.Item>
);

export const DropdownMenuSeparator: React.FC = () => (
  <DropdownMenuPrimitive.Separator className="h-px bg-border mx-2 my-1" />
);
