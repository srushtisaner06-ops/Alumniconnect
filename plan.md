# AlumniConnect Feature Audit and Implementation Plan

## Implementation status

| Phase | Status | Notes |
|---|---|---|
| 0 Foundation and security | Done | Roles, sessions, audit log, expiring links, rate limits, privacy levels, storage, migrations. See `PHASE0_CHANGES.md`. |
| 1 Profiles and forms | Done (department deferred) | **1A:** proof upload + review, income range, consent. **1B:** `career_events` timeline with back-fill, structured profile fields, role-specific menus/pages, invites, member network, proof reminders. Department was deliberately left out. The public form is unchanged apart from the Verification section. |
| 2 Directory and analytics | Next | Filters (domain, company, college, country, batch, designation, experience, skills), sorting, filtered exports, domain/country/designation analytics. A basic search already exists in the member network. |
| 3–6 | Not started | |

## Scope

This document records the feature audit and the remaining implementation plan. Only this file is being added; no application, schema, configuration, test, or existing project file is changed by this plan.

## Current audit

| Feature | Status | Finding |
|---|---|---|
| Registration and profiles | Partial | Name, email, phone, batch, placement, higher studies, entrepreneurship and resubmission exist. WhatsApp, department, documents, consent visibility and structured career history are missing. |
| Advanced search and filters | Partial | Search, status/category filters and exports exist. Domain, company, college, country, batch, designation, experience, sorting and filtered exports are missing. |
| Alumni Circles | Missing | No skills/interests matching, compatibility score, connection requests or communities. |
| Mentorship Hub | Missing | No mentor registration, matching, requests or connection tracking. |
| Opportunity/referral board | Missing | Reminder campaigns are not an opportunity board. Jobs, internships, referrals, scholarships and research posts are missing. |
| Startup collaboration | Partial | Entrepreneurship records and reports exist; startup showcase, co-founder discovery and collaboration requirements are missing. |
| Events/networking | Missing | No events, registration, attendance or networking sessions. |
| Career timeline | Partial | Reminder history exists, but not career events, promotions, job changes or achievements. |
| Analytics | Partial | Placement, higher studies, entrepreneurship, recruiter, institution and batch reports exist. Domain, country, designation and map views are missing. |
| Faculty/admin dashboard | Partial | Admin login, records, imports, exports, reminders and reports exist. Roles, permissions, verification workflow, configurable forms and user management are missing. |
| AI features | Missing | No recommendations, matching or trend insights. These should follow structured profile and interaction data. |
| Security/privacy | Partial | JWT login and protected admin APIs exist. Public tokens do not expire, rate limiting is absent, and there are no document controls, consent visibility, RBAC or audit logs. |

## Implementation plan

### Phase 0: foundation and security

- Add users, roles and permissions for Admin, Faculty, Alumni and Student.
- Add session/account management, password reset structure and audit logs.
- Add profile visibility choices: private, institution-only, alumni-only and public.
- Add expiring and revocable public-form tokens plus rate limiting.
- Add a private document-storage abstraction with file type/size validation.
- Keep SQLite for local development, but design new tables and services to migrate cleanly to PostgreSQL.

### Phase 1: complete profiles and forms

- Add department, WhatsApp number, country, city, professional domain, skills, interests, years of experience, designation and profile links.
- Expand placement, higher-studies and entrepreneurship forms without breaking existing imports.
- Add verification documents with pending, approved and rejected states, rejection reasons and authorized downloads.
- Add a structured append-only career event model for graduation, first job, promotion, job change, higher studies, entrepreneurship and achievements.
- Migrate existing JSON career details into structured fields where possible.

### Phase 2: directory and analytics

- Add filters for domain, company, college/university, country, batch, career type, designation, experience and skills.
- Add sorting by name, batch, experience and recent activity.
- Make CSV/Excel exports use the active filter set.
- Add domain-wise, country-wise and designation-wise analytics.
- Add interactive charts and a global map only after location data is normalized and consent-aware.

### Phase 3: Alumni Circles and mentorship

- Add skills, interests and domain tags.
- Add connection requests with pending, accepted, rejected and blocked states.
- Calculate an explainable compatibility score using shared domain, skills, interests, batch, location and goals.
- Add moderated interest communities.
- Add mentor profiles with expertise, availability, preferred mentee type and capacity.
- Add mentorship requests, acceptance, status tracking, closure and feedback.
- Keep contact details private until consent or an accepted connection.

### Phase 4: opportunities and startup collaboration

- Add moderated, owned and expiring posts for jobs, internships, referrals, scholarships and research.
- Add student interest/application tracking and post reporting.
- Add startup profiles linked to alumni and reuse existing venture records as initial data.
- Add collaboration requirements for co-founders, developers, designers, marketing, advisors and other roles.
- Add searchable startup and collaborator discovery.

### Phase 5: events and networking

- Add event creation, editing, moderation, capacity and expiry.
- Support reunions, webinars, workshops and networking sessions.
- Add registration, cancellation, attendance and follow-up tracking.
- Reuse the existing email/Telegram campaign infrastructure for event reminders.

### Phase 6: AI-assisted features

- Add alumni, mentor and opportunity recommendations only after structured profile, opportunity and interaction data exists.
- Provide an explanation for every recommendation and retain a deterministic non-AI fallback.
- Use only consented and visibility-eligible data for AI processing.
- Add recommendation feedback for quality monitoring.

## Required data interfaces

Add separate models/tables for:

- `profiles`, `profile_skills`, `profile_interests`
- `career_events`
- `verification_documents`, `profile_visibility`
- `users`, `roles`, `permissions`, `audit_logs`
- `connection_requests`
- `communities`, `community_members`
- `mentor_profiles`, `mentorship_requests`
- `opportunities`, `opportunity_interests`
- `startups`, `startup_requirements`
- `events`, `event_registrations`, `attendance`
- `recommendation_feedback`

Keep the existing `offers`, `higher_studies`, `ventures`, import-history and reminder tables compatible during migration.

## Tunnel and URL recommendation

The current frontend runs on port `5173`, proxies `/api` to port `8000`, and uses `PUBLIC_URL` for alumni links. Any stable tunnel must therefore expose the frontend and use:

```env
PUBLIC_URL=https://your-stable-public-url
CORS_ORIGINS=https://your-stable-public-url
```

Recommended order:

1. **ngrok** for the easiest repeated local sharing. Its account-assigned dev domain is stable across restarts.
2. **Microsoft Dev Tunnels** for a Windows-friendly persistent hostname.
3. **Tailscale Funnel** if Tailscale is already in use and public exposure is approved.
4. **localhost.run** for quick temporary SSH-based sharing only.
5. **Cloudflare Named Tunnel** if retaining Cloudflare; use a named tunnel and controlled hostname instead of Quick Tunnel random URLs.

Do not expose the current public token form and personal data for real users until token expiry, rate limiting, privacy visibility and document protection are implemented.

## Acceptance and testing plan

- Preserve all current import, form, reminder, Telegram and reporting regression tests.
- Test every new profile field and career event.
- Test role and permission boundaries for Admin, Faculty, Alumni and Student.
- Test document validation, private access, approval and rejection.
- Test every individual filter, combined filters, sorting and filtered exports.
- Test connection request state transitions and blocking.
- Test deterministic mentor matching and compatibility explanations.
- Test opportunity/startup publishing, moderation, expiry and applications.
- Test event capacity, registration, cancellation and attendance.
- Test hidden fields and documents are never returned without permission.
- Test expired/revoked tokens, rate limiting, unauthorized exports and audit logging.
- Test that generated links use `PUBLIC_URL` and that public frontend `/api` requests reach the backend through the selected tunnel.

## Completion order

Implement Phases 0–2 first because they provide the secure, structured data foundation. Implement Phases 3–5 next for the platform’s main identity: Discover, Connect and Collaborate. Implement Phase 6 last, after enough structured data exists for recommendations to be useful and explainable.
