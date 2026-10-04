/**
 * Local account store for self-hosted Peeker, modeled on Kwerry:
 * scrypt-hashed passwords, first-run admin seed, extra accounts from the
 * login page. Users live in a JSON file next to the app (gitignored).
 */
import { randomBytes, scryptSync, timingSafeEqual } from "node:crypto";
import { mkdirSync, readFileSync, writeFileSync, existsSync } from "node:fs";
import { join } from "node:path";

export interface UserRecord {
  username: string;
  passwordHash: string;
  createdAt: string;
}

const DATA_DIR = join(process.cwd(), "data");
const USERS_PATH = join(DATA_DIR, "users.json");

const SCRYPT_KEYLEN = 64;

function hashPassword(password: string, salt?: Buffer): string {
  const s = salt ?? randomBytes(16);
  const derived = scryptSync(password, s, SCRYPT_KEYLEN);
  return `scrypt:${s.toString("hex")}:${derived.toString("hex")}`;
}

function verifyPassword(password: string, stored: string): boolean {
  const parts = stored.split(":");
  if (parts.length !== 3 || parts[0] !== "scrypt") return false;
  const salt = Buffer.from(parts[1], "hex");
  const want = Buffer.from(parts[2], "hex");
  const got = scryptSync(password, salt, want.length);
  return timingSafeEqual(got, want);
}

function readUsers(): UserRecord[] {
  if (!existsSync(USERS_PATH)) return [];
  try {
    const raw = JSON.parse(readFileSync(USERS_PATH, "utf8")) as UserRecord[];
    return Array.isArray(raw) ? raw : [];
  } catch {
    return [];
  }
}

function writeUsers(users: UserRecord[]): void {
  mkdirSync(DATA_DIR, { recursive: true });
  writeFileSync(USERS_PATH, JSON.stringify(users, null, 2), "utf8");
}

export function userCount(): number {
  return readUsers().length;
}

export function findUser(username: string): UserRecord | null {
  const key = username.trim().toLowerCase();
  return readUsers().find((u) => u.username === key) ?? null;
}

/**
 * Append an account. Private on purpose: there is no self-registration, so the only
 * callers are the first-run seed below and nothing that a request can reach. Accounts
 * are created by setting SEED_ADMIN_USERNAME / SEED_ADMIN_PASSWORD in .env.local
 * (Grafana's model) and are then owned by data/users.json.
 */
function insertUser(username: string, password: string): UserRecord {
  const key = username.trim().toLowerCase();
  const record: UserRecord = {
    username: key,
    passwordHash: hashPassword(password),
    createdAt: new Date().toISOString(),
  };
  const users = readUsers();
  users.push(record);
  writeUsers(users);
  return record;
}

export function checkPassword(username: string, password: string): UserRecord | null {
  const user = findUser(username);
  if (!user) return null;
  return verifyPassword(password, user.passwordHash) ? user : null;
}

export function changePassword(username: string, current: string, next: string): void {
  const users = readUsers();
  const idx = users.findIndex((u) => u.username === username.trim().toLowerCase());
  if (idx < 0) throw new Error("User not found.");
  if (!verifyPassword(current, users[idx].passwordHash)) {
    throw new Error("Current password is incorrect.");
  }
  if (!next || next.length < 8) throw new Error("New password must be at least 8 characters.");
  users[idx] = { ...users[idx], passwordHash: hashPassword(next) };
  writeUsers(users);
}

/**
 * First-run admin (Grafana's model): SEED_ADMIN_USERNAME / SEED_ADMIN_PASSWORD from
 * .env.local when set, otherwise `admin` with a random password returned once.
 *
 * Env credentials are a *first-boot* input, not a live source of truth: this no-ops
 * as soon as one account exists, so editing SEED_ADMIN_PASSWORD afterwards has no
 * effect — data/users.json owns the password from then on. Change it under Settings,
 * or delete the account and restart to re-seed.
 *
 * Returns a notice for the operator when a password was generated, so a fresh
 * install with no configured password can still be signed into.
 */
export function ensureSeedAdmin(): string | null {
  if (userCount() > 0) return null;
  const username = (process.env.SEED_ADMIN_USERNAME ?? "admin").trim() || "admin";
  const configured = process.env.SEED_ADMIN_PASSWORD;
  const password = configured && configured.length >= 8
    ? configured
    : randomBytes(12).toString("base64url");
  insertUser(username, password);
  if (configured && configured.length >= 8) return null;
  return `First-run admin created. Username: ${username}  Password: ${password}\nSign in, then change it under Settings.`;
}
