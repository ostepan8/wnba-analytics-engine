/* Data access. Same-origin relative paths: the app is served by the API that
   answers these, so there is no base URL to configure and no CORS grant needed.

   Every data path goes under /api. The client owns routing, so /players/36 is a
   page; without the prefix the endpoint of the same name shadowed it and
   navigating to a player rendered raw JSON. */

import { useEffect, useRef, useState } from "react";

/** Object storage, served straight to the browser and cached by the CDN. */
export const ASSETS = "https://s3.onephos.com/wnba-assets";

export const teamLogo = (teamId: number | null | undefined) =>
  teamId == null ? null : `${ASSETS}/teams/${teamId}.png`;

export const playerImage = (playerId: number | null | undefined) =>
  playerId == null ? null : `${ASSETS}/players/${playerId}.png`;

export class ApiError extends Error {
  constructor(readonly status: number, readonly path: string) {
    super(`${path} responded ${status}`);
  }
}

export const API_PREFIX = "/api";

export async function getJSON<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${API_PREFIX}${path}`, { signal });
  if (!response.ok) throw new ApiError(response.status, path);
  return (await response.json()) as T;
}

export type Query<T> = {
  data: T | undefined;
  error: Error | undefined;
  loading: boolean;
};

/**
 * Fetch on mount and whenever `path` changes.
 *
 * The in-flight request is aborted when the path changes or the component
 * unmounts. Without that, clicking quickly through three players races three
 * responses and whichever lands last wins -- which is not necessarily the one
 * the user is looking at.
 */
export function useQuery<T>(path: string | null): Query<T> {
  const [state, setState] = useState<Query<T>>({
    data: undefined,
    error: undefined,
    loading: path !== null,
  });
  // Survives StrictMode's double-invoke without firing two real requests.
  const latest = useRef<string | null>(null);

  useEffect(() => {
    if (path === null) {
      setState({ data: undefined, error: undefined, loading: false });
      return;
    }
    latest.current = path;
    const controller = new AbortController();
    setState((previous) => ({ ...previous, loading: true, error: undefined }));

    getJSON<T>(path, controller.signal)
      .then((data) => {
        if (latest.current === path) setState({ data, error: undefined, loading: false });
      })
      .catch((error: Error) => {
        if (error.name === "AbortError") return;
        if (latest.current === path) setState({ data: undefined, error, loading: false });
      });

    return () => controller.abort();
  }, [path]);

  return state;
}

/* --- response shapes ---------------------------------------------------- */

export interface StandingRow {
  team_id: number;
  name: string;
  abbreviation: string;
  conference: string | null;
  wins: number | null;
  losses: number | null;
  win_percentage: string | null;
  games_behind: string | null;
  home_record: string | null;
  away_record: string | null;
  playoff_seed: number | null;
}

export interface TeamRow extends StandingRow {
  id: number;
  is_franchise: boolean;
}

export interface RosterRow {
  player_id: number;
  full_name: string;
  position: string | null;
  jersey_number: string | null;
  games_played: number;
  points: string | null;
  rebounds: string | null;
  assists: string | null;
  minutes: string | null;
}

export interface ScheduleRow {
  id: number;
  start_time: string;
  status: string;
  home_score: number | null;
  away_score: number | null;
  is_home: boolean;
  opponent_id: number;
  opponent: string;
  opponent_abbr: string;
  /** Closing consensus, from THIS team's perspective — already sign-flipped
      for road games, so it never needs flipping at the call site. */
  spread: string | null;
  total: string | null;
  books: number | null;
  /** null on a push, and for anything not yet final. */
  covered: boolean | null;
  went_over: boolean | null;
}

export interface PlayerRow {
  player_id: number;
  full_name: string;
  position: string | null;
  team_abbr: string | null;
  team_id: number | null;
  games_played: number;
  points: string | null;
  minutes: string | null;
  has_image: boolean;
}

export interface PlayerProfile {
  player_id: number;
  full_name: string;
  position: string | null;
  height: string | null;
  weight: string | null;
  jersey_number: string | null;
  college: string | null;
  age: number | null;
  has_image: boolean;
}

export interface PlayerSeason {
  season: number;
  team_abbr: string | null;
  games_played: number;
  points: string | null;
  rebounds: string | null;
  assists: string | null;
  steals: string | null;
  blocks: string | null;
  minutes: string | null;
  field_goal_pct: string | null;
  three_point_pct: string | null;
}

export interface GameLogRow {
  game_id: number;
  start_time: string;
  status: string;
  season: number;
  points: number | null;
  rebounds: number | null;
  assists: number | null;
  steals: number | null;
  blocks: number | null;
  turnovers: number | null;
  minutes: number | null;
  field_goals_made: number | null;
  field_goals_attempted: number | null;
  three_pointers_made: number | null;
  three_pointers_attempted: number | null;
  plus_minus: number | null;
  opponent_abbr: string;
  opponent_id: number;
  is_home: boolean;
  home_score: number | null;
  away_score: number | null;
}

export interface GameRow {
  id: number;
  season: number;
  season_type: string | null;
  start_time: string;
  status: string;
  home_score: number | null;
  away_score: number | null;
  venue_name: string | null;
  home_team: string;
  home_abbr: string;
  away_team: string;
  away_abbr: string;
}

export interface GameDetail extends GameRow {
  attendance: number | null;
  home_team_id?: number;
  away_team_id?: number;
}

export interface BoxScoreRow {
  player_id: number;
  full_name: string;
  team_id: number;
  team_abbr: string;
  starter: boolean | null;
  minutes: number | null;
  points: number | null;
  rebounds: number | null;
  assists: number | null;
  steals: number | null;
  blocks: number | null;
  turnovers: number | null;
  fouls: number | null;
  plus_minus: number | null;
  field_goals_made: number | null;
  field_goals_attempted: number | null;
  three_pointers_made: number | null;
  three_pointers_attempted: number | null;
  free_throws_made: number | null;
  free_throws_attempted: number | null;
}

export interface FlowPlay {
  sequence: number;
  period: number;
  clock: string | null;
  home_score: number;
  away_score: number;
  margin: number;
  description: string | null;
}

export interface ShotCell {
  x: number;
  y: number;
  attempts: number;
  makes: number;
  points: number;
}

export interface ShotZone {
  zone: string;
  attempts: number;
  makes: number;
  avg_distance: string | null;
}

export interface ShotChartResponse {
  season: number;
  bin_size: number;
  cells: ShotCell[];
  zones: ShotZone[];
  attempts: number;
  points_per_attempt: number | null;
}

export interface EfficiencyRow {
  player_id: number;
  full_name: string;
  team_abbr: string | null;
  games_played: number;
  usage_pct: string | null;
  true_shooting: string | null;
  net_rating: string | null;
  minutes: string | null;
}

export interface LeaderRow {
  player_id: number;
  full_name: string;
  team_abbr: string | null;
  games_played: number;
  points: string;
  rebounds: string;
  assists: string;
  steals: string;
  blocks: string;
  minutes: string;
}

export interface MarketPrice {
  provider: string;
  implied_probability: string;
  captured_at: string;
  side: "home" | "away";
}

export interface OddsRow {
  vendor: string;
  captured_at: string;
  moneyline_home_odds: number | null;
  moneyline_away_odds: number | null;
}

export interface DivergenceVenue {
  venue: string;
  observations: number;
  graded: number;
  price_survived: number;
  survival_checked: number;
  mean_edge: string | null;
  mean_clv: string | null;
  clv_graded: number;
  won: number;
  settled: number;
}

export interface JobHealth {
  job_name: string;
  last_run_at: string | null;
  last_success_at: string | null;
  last_status: string | null;
  last_error: string | null;
  failures_24h: number | null;
  runs_24h: number | null;
  enabled: boolean;
  scheduled: boolean;
  description: string;
}

export interface DatasetSummary {
  games: number;
  games_final: number;
  teams: number;
  players: number;
  market_price_snapshots: number;
  sportsbook_game_odds: number;
  divergence_observations: number;
  earliest_game: string;
  latest_game: string;
  latest_market_price: string | null;
  latest_sportsbook_odds: string | null;
}

/* --- line data ----------------------------------------------------------- */

export interface ClosingLine {
  game_id: number;
  spread_home: string | null;
  total: string | null;
  moneyline_home: string | null;
  moneyline_away: string | null;
  books: number;
  closed_at: string;
  home_score: number | null;
  away_score: number | null;
  status: string;
  /** null on a push, and for anything not yet final. */
  home_covered: boolean | null;
  went_over: boolean | null;
}

export interface LineMovementRow {
  vendor: string;
  captured_at: string;
  spread_home_value: string | null;
  spread_home_odds: number | null;
  total_value: string | null;
  total_over_odds: number | null;
  total_under_odds: number | null;
  moneyline_home_odds: number | null;
  moneyline_away_odds: number | null;
}

export interface TeamBettingRecord {
  spread_games: number;
  covers: number;
  non_covers: number;
  overs: number;
  unders: number;
  avg_total: string | null;
  avg_spread: string | null;
}

export interface PropSummaryRow {
  prop_type: string;
  games: number;
  avg_line: string | null;
  avg_realized: string | null;
  overs: number;
  unders: number;
  pushes: number;
}

export interface PropLogRow {
  game_id: number;
  start_time: string;
  books: number;
  line: string;
  realized: number;
  result: "over" | "under" | "push";
  opponent_abbr: string;
  opponent_id: number;
}

export interface PropMarketRow {
  prop_type: string;
  games: number;
  overs: number;
  unders: number;
  pushes: number;
  avg_line: string | null;
}

/** Prop keys are snake_case in the database; this is how they read on screen. */
export const PROP_LABELS: Record<string, string> = {
  points: "Points",
  rebounds: "Rebounds",
  assists: "Assists",
  threes: "Threes made",
  points_rebounds_assists: "Pts + Reb + Ast",
  points_rebounds: "Pts + Reb",
  points_assists: "Pts + Ast",
  rebounds_assists: "Reb + Ast",
};

export const propLabel = (key: string) => PROP_LABELS[key] ?? key;

/** A home spread of -6.5 is written "-6.5"; +6.5 needs its sign shown. */
export const spreadLabel = (value: string | null) =>
  value == null ? "—" : `${Number(value) > 0 ? "+" : ""}${Number(value).toFixed(1)}`;

export const moneylineLabel = (value: string | number | null) =>
  value == null ? "—" : `${Number(value) > 0 ? "+" : ""}${Math.round(Number(value))}`;
