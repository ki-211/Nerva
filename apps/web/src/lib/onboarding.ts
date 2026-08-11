import { clientLogger } from './clientLogger';

const STORAGE_KEY = 'nerva.onboarding';
const MAX_REMEMBERED_USERS = 20;

type OnboardingRecord = { users: string[] };

function readRecord(): OnboardingRecord {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return { users: [] };
    const parsed = JSON.parse(raw) as Partial<OnboardingRecord> | null;
    const users = parsed?.users;
    if (!Array.isArray(users)) return { users: [] };
    return { users: users.filter((value): value is string => typeof value === 'string' && value.length > 0) };
  } catch (cause) {
    // A corrupted or unavailable store must not block startup; treat it as a fresh install.
    clientLogger.warn('onboarding_state_unreadable', { operation: 'onboarding.read', cause });
    return { users: [] };
  }
}

/** User ids that already finished the wizard on this device. Empty means a fresh install. */
export function completedUserIds(): string[] {
  return readRecord().users;
}

export function isOnboardingComplete(userId: string): boolean {
  return readRecord().users.includes(userId);
}

export function markOnboardingComplete(userId: string): void {
  const { users } = readRecord();
  if (users.includes(userId)) return;
  const next = [...users, userId].slice(-MAX_REMEMBERED_USERS);
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify({ users: next } satisfies OnboardingRecord));
  } catch (cause) {
    // The wizard also tracks completion in React state, so a failed write only means
    // the wizard reappears on the next launch — never a blocked or repeating wizard.
    clientLogger.warn('onboarding_state_unwritable', { operation: 'onboarding.write', cause });
  }
}
