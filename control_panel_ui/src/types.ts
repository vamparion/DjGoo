export type Track = {
  title: string;
  uri?: string;
};

export type Playlist = {
  name: string;
  track_count: number;
  tracks: Track[];
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
};

export type HealthItem = {
  status: string;
  pid?: string;
  detail?: string;
};

export type ControlState = {
  playback: {
    title: string;
    artist: string;
    station: string;
    source: string;
    remaining: string;
    queue_count: number;
  };
  queue: Track[];
  playlists: Playlist[];
  stations: Station[];
  active_station: Station | null;
  health: Record<string, HealthItem>;
  logs: Record<string, string[]>;
};
