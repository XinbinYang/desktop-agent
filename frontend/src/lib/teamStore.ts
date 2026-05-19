export interface Team {
  id: string;
  name: string;
  color: string;
  memberPaneIds: string[]; // SessionPane.id (not leaf node id)
  createdAt: number;
}

const TEAMS_KEY = 'desktop-agent-teams';
const TEAM_COLORS = ['#3b82f6', '#ef4444', '#10b981', '#f59e0b', '#8b5cf6', '#ec4899', '#06b6d4', '#f97316'];

let _colorIdx = 0;

function nextColor(): string {
  return TEAM_COLORS[_colorIdx++ % TEAM_COLORS.length];
}

export function loadTeams(): Team[] {
  try {
    const raw = localStorage.getItem(TEAMS_KEY);
    if (!raw) return [];
    const data = JSON.parse(raw);
    if (Array.isArray(data)) {
      _colorIdx = data.length;
      return data as Team[];
    }
    return [];
  } catch {
    return [];
  }
}

export function saveTeams(teams: Team[]): void {
  try {
    localStorage.setItem(TEAMS_KEY, JSON.stringify(teams));
  } catch { /* ignore */ }
}

export function createTeam(name: string): Team {
  return {
    id: `team_${Date.now()}`,
    name: name || '新团队',
    color: nextColor(),
    memberPaneIds: [],
    createdAt: Date.now(),
  };
}

export function getTeamForPane(teams: Team[], paneId: string): Team | undefined {
  return teams.find((t) => t.memberPaneIds.includes(paneId));
}

export function addPaneToTeam(teams: Team[], teamId: string, paneId: string): Team[] {
  return teams.map((t) => {
    if (t.memberPaneIds.includes(paneId)) {
      return { ...t, memberPaneIds: t.memberPaneIds.filter((id) => id !== paneId) };
    }
    if (t.id === teamId) {
      return { ...t, memberPaneIds: [...t.memberPaneIds, paneId] };
    }
    return t;
  });
}

export function removePaneFromTeam(teams: Team[], paneId: string): Team[] {
  return teams
    .map((t) => ({ ...t, memberPaneIds: t.memberPaneIds.filter((id) => id !== paneId) }))
    .filter((t) => t.memberPaneIds.length > 0);
}

export function deleteTeam(teams: Team[], teamId: string): Team[] {
  return teams.filter((t) => t.id !== teamId);
}
