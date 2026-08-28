import { Activity, ShieldAlert, ShieldCheck, ShieldOff } from 'lucide-react'

/**
 * Presentation for each backend ShieldState.
 *
 * This is a lookup table, not a state machine: the keys mirror the enum in
 * `backend/app/models/domain.py`, and the UI renders whichever state the
 * engine reported. Adding a state here does not create one.
 *
 * Kept out of the component file so editing it does not invalidate fast
 * refresh for the status bar.
 */
export const SHIELD_STATES = {
  ARMED: {
    label: 'ARMED / MONITORING',
    short: 'ARMED',
    caption: 'Watching the position. No intervention required.',
    tone: 'safe',
    Icon: ShieldCheck,
    pulse: false,
  },
  ALERT: {
    label: 'ALERT',
    short: 'ALERT',
    caption: 'Risk threshold crossed. Strategies generated and scored.',
    tone: 'warn',
    Icon: ShieldAlert,
    pulse: true,
  },
  PROTECTING: {
    label: 'PROTECTING',
    short: 'PROTECTING',
    caption: 'Executing the selected rescue (simulated).',
    tone: 'warn',
    Icon: Activity,
    pulse: true,
  },
  PROTECTED: {
    label: 'PROTECTED',
    short: 'PROTECTED',
    caption: 'Rescue landed. Target Health Factor restored.',
    tone: 'safe',
    Icon: ShieldCheck,
    pulse: false,
  },
  SKIPPED: {
    label: 'STOOD DOWN',
    short: 'STOOD DOWN',
    caption: 'Risk detected, but no rescue is worth running.',
    tone: 'danger',
    Icon: ShieldOff,
    pulse: false,
  },
}

export const shieldState = (key) => SHIELD_STATES[key] ?? SHIELD_STATES.ARMED
