"use client";

/**
 * Every icon in the UI lives here. No emoji or text glyphs anywhere else.
 *
 * Phosphor calls `createContext` at module scope, so this file is a Client
 * Component boundary: that keeps it out of the server graph (where
 * `createContext` does not exist) while still letting Server Components render
 * these icons, since the API is only className / size / title.
 *
 * Glyphs come from Phosphor: one allowed family per project, one standardized
 * weight, and no hand-rolled icon paths (taste-SKILL 3.C). The shared `.icon`
 * rule in globals.css sizes them to 1em so they track the label next to them,
 * and extra classes pass through `className` (e.g. `spin`). Icons are
 * decorative by default; pass `title` when the icon alone carries the meaning.
 */

import type { ElementType } from "react";
import {
  ArrowClockwise,
  ArrowRight,
  Bell,
  ChartLineUp,
  Check,
  DownloadSimple,
  GearSix,
  List,
  MagnifyingGlass,
  Moon,
  PencilSimple,
  Play,
  SignOut,
  SquaresFour,
  Star,
  Storefront,
  Sun,
  Trash,
  UploadSimple,
  User,
  X,
} from "@phosphor-icons/react";

export type IconProps = {
  className?: string;
  /** Accessible name. Leave it out for purely decorative icons. */
  title?: string;
  size?: number | string;
};

/**
 * ElementType instead of a hand-copied prop type: Phosphor types `role` and
 * `focusable` as DOM unions, and duplicating those here only creates drift.
 * The wrapper owns the props that matter (class, size, weight, a11y name).
 */
function icon(GlyphComponent: ElementType, weight: "regular" | "fill" = "regular") {
  return function Icon({ className, title, size = "1em" }: IconProps) {
    return (
      <GlyphComponent
        className={className ? `icon ${className}` : "icon"}
        size={size}
        weight={weight}
        role={title ? "img" : undefined}
        aria-label={title}
        aria-hidden={title ? undefined : true}
        focusable="false"
      />
    );
  };
}

/** Sun. Shown while the theme is dark (click goes back to light). */
export const SunIcon = icon(Sun);
/** Crescent moon. Shown while the theme is light (click goes to dark). */
export const MoonIcon = icon(Moon);
/** Chasing arrow: refresh. Add `className="spin"` while a request is in flight. */
export const RefreshIcon = icon(ArrowClockwise);
/** Tick: confirm / acknowledge actions. */
export const CheckIcon = icon(Check);
/** Cross: dismiss banners and close dialogs. */
export const CloseIcon = icon(X);
/** Three rules: the burger that opens the mobile nav drawer. */
export const ListIcon = icon(List);
/** Solid triangle: start a scrape/job. */
export const PlayIcon = icon(Play, "fill");
/** Pencil: edit a row's fields (business name, Maps link, etc). */
export const EditIcon = icon(PencilSimple);
/** Bin: destructive delete of a whole record. */
export const TrashIcon = icon(Trash);
/** Arrow: links that navigate to another page. */
export const ArrowRightIcon = icon(ArrowRight);
/** Rating star, filled. */
export const StarIcon = icon(Star, "fill");
/** Rating star, outline: thinner presence so a row of them stays quiet. */
export const StarOutlineIcon = icon(Star);
/** Arrow into a tray: file upload. */
export const UploadIcon = icon(UploadSimple);
/** Arrow out of a tray: report / CSV download. */
export const DownloadIcon = icon(DownloadSimple);
/** Grid: overview dashboard. */
export const OverviewIcon = icon(SquaresFour);
/** Shopfront: business listings. */
export const BusinessesIcon = icon(Storefront);
/** Magnifier: analyze / research. */
export const AnalyzeIcon = icon(MagnifyingGlass);
/** Bars: performance charts. */
export const PerformanceIcon = icon(ChartLineUp);
/** Bell: alerts. */
export const AlertsIcon = icon(Bell);
/** Person: signed-in user trigger (Kwerry side-foot). */
export const UserIcon = icon(User);
/** Arrow leaving a door: sign out, in the profile popover and its confirm dialog. */
export const SignOutIcon = icon(SignOut);
/** Star: reviews inbox. */
export const ReviewsIcon = icon(Star);
/** Gear: settings (password, database backup/restore). */
export const SettingsIcon = icon(GearSix);
