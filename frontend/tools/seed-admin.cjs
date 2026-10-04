/**
 * Recreate the local admin account in frontend/data/users.json, using the same
 * scrypt format as lib/users.ts. Needed when the account store is wiped and you
 * cannot sign in to reach Settings.
 *
 * Credentials come from the environment, never a literal in this file:
 *   SEED_ADMIN_USERNAME=... SEED_ADMIN_PASSWORD=... node tools/seed-admin.cjs
 *
 * The earlier version hardcoded the password here, which put a real credential
 * in tracked source. It also hardcoded the username, so it silently rewrote
 * whatever account it was pointed at.
 */
const { randomBytes, scryptSync } = require("node:crypto");
const { mkdirSync, writeFileSync, existsSync, readFileSync } = require("node:fs");
const { join } = require("node:path");

const DATA_DIR = join(process.cwd(), "data");
const USERS_PATH = join(DATA_DIR, "users.json");
const SCRYPT_KEYLEN = 64;

const username = (process.env.SEED_ADMIN_USERNAME ?? "").trim();
const password = process.env.SEED_ADMIN_PASSWORD ?? "";

if (!username) {
  console.error("set SEED_ADMIN_USERNAME before running");
  process.exit(1);
}
if (password.length < 8) {
  console.error("SEED_ADMIN_PASSWORD must be at least 8 characters");
  process.exit(1);
}

function hashPassword(plain) {
  const s = randomBytes(16);
  const derived = scryptSync(plain, s, SCRYPT_KEYLEN);
  return `scrypt:${s.toString("hex")}:${derived.toString("hex")}`;
}

mkdirSync(DATA_DIR, { recursive: true });
let users = [];
if (existsSync(USERS_PATH)) {
  try {
    users = JSON.parse(readFileSync(USERS_PATH, "utf8"));
    if (!Array.isArray(users)) users = [];
  } catch {
    users = [];
  }
}

const key = username.toLowerCase();
const existing = users.find((u) => u.username === key);
const record = {
  username: key,
  passwordHash: hashPassword(password),
  createdAt: new Date().toISOString(),
};
if (existing) {
  existing.passwordHash = record.passwordHash;
  console.log(`updated existing user ${key}`);
} else {
  users.push(record);
  console.log(`created user ${key}`);
}
writeFileSync(USERS_PATH, JSON.stringify(users, null, 2), "utf8");
console.log("wrote", USERS_PATH);
console.log("users:", users.map((u) => u.username).join(", "));
