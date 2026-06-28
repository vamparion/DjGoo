import type { ControlState } from "../types";

export type CommandSender = (action: string, payload?: Record<string, unknown>) => Promise<void>;

export type PanelProps = {
  state: ControlState;
  send: CommandSender;
};
