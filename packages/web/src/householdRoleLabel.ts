import { MyRole, type Role } from '@/api';

const roleLabels: Record<MyRole | Role, string> = {
  [MyRole.Owner]: 'Haushaltsleitung',
  [MyRole.Member]: 'Mitglied'
};

export function householdRoleLabel(role: MyRole | Role) {
  return roleLabels[role];
}
