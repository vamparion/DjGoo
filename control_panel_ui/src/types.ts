export type Track = {
  id?: string;
  title: string;
  uri?: string;
  artist?: string;
  requester?: string;
  request_type?: string;
};

export type Playlist = {
  name: string;
  track_count: number;
  tracks: Track[];
  description?: string; artwork_url?: string; folder?: string; tags?: string[]; smart_query?: string;
};

export type Station = {
  id: string;
  name: string;
  seed: string;
  liked_count: number;
  more_like_count: number;
  less_like_count: number;
  banned_count: number;
  skipped_count: number;
  last_track?: Track | null;
  liked: Track[];
  more_like: Track[];
  less_like: Track[];
  banned: Track[];
  skipped: Track[];
  played: Track[]; recent: Track[];
  feedback_history: Array<{ id: string; action: string; track: Track; created_at: string }>;
  snapshots: Array<{ id: string; name: string; created_at: string }>;
  familiar_percent: number; balanced_percent: number; discovery_percent: number;
  artist_spacing: number; song_spacing: number; seed_type: string; seed_examples: string[];
  last_selection_reason?: string; last_drift_score?: number;
};

export type HealthItem = {
  status: string;
  pid?: string;
  detail?: string;
};

export type ControlState = {
  generated_at?: number;
  session?: { role: string; display_name: string; discord_user_id?: string; guild_id?: string; device_id?: string };
  capabilities?: { system_management?: boolean; diagnostics?: boolean; library_management?: boolean; settings_management?: boolean };
  playback: {
    title: string;
    artist: string;
    station: string;
    source: string;
    remaining: string;
    queue_count: number;
    requester?: string;
    state?: string;
  };
  queue: Track[];
  playlists: Playlist[];
  stations: Station[];
  active_station: Station | null;
  health: Record<string, HealthItem>;
  logs: Record<string, string[]>;
  timeline: Array<{ time: string; title: string; detail: string }>;
  history: Array<Track & { played_at: number; mode: string; station: string }>;
  gaming: {
    settings: {
      ranked_mode: boolean;
      per_user_queue_limit: number;
      round_robin: boolean;
      vote_thresholds: Record<string, number>;
      explicit_policy: "allow" | "warn" | "reject";
      volume_normalization: boolean;
      normalization_target: number;
      crossfade_enabled: boolean;
      crossfade_seconds: number;
      preload_enabled: boolean;
      media_keys_enabled: boolean;
    };
    profiles: Array<{ id: string; username: string; role: string; last_seen: number }>;
  };
  players?: Array<{ id: string; discord_user_id: string; username: string; role: string; device_name: string; device_type: string; last_seen: number; online: boolean; device_count?: number }>;
};
