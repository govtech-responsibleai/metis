import assert from "node:assert/strict";
import { test } from "node:test";
import { renderToStaticMarkup } from "react-dom/server";
import { Router } from "wouter";
import {
  adminReducer,
  AdminRoute,
  AdminTaskBody,
  AdminView,
  credentialsText,
  initialAdminState,
  type AdminEvent,
  type AdminState,
  type AdminTask,
} from "./AdminPage";
import { LoginSessionProvider } from "./LoginGate";
import { control, text } from "./markup.test-helper";
import { TargetRail } from "./TargetRail";
import type { UserAccount } from "./transport/api";
import { initials } from "./ui";

const lead: UserAccount = {
  id: "a1",
  username: "workshop-lead",
  created_at: "2026-11-14T08:30:00Z",
  admin: true,
};
const otter: UserAccount = {
  id: "b2",
  username: "curious-otter",
  created_at: "2026-11-14T09:00:00Z",
  admin: false,
};
const password = "k7mwp-3xr9t";

const after = (...events: AdminEvent[]): AdminState =>
  events.reduce(adminReducer, initialAdminState);

const actions = {
  dispatch: () => {},
  onCreate: () => {},
  onReset: () => {},
  onDelete: () => {},
};

const view = (state: AdminState, currentUserId: string | null = lead.id) =>
  renderToStaticMarkup(
    <AdminView state={state} currentUserId={currentUserId} {...actions} />,
  );

// The Modal renders in a portal, which static markup does not draw, so the tests render the
// content of the open dialog on its own.
const dialog = (task: AdminState["task"]) => {
  assert.notEqual(task.kind, "idle");
  return renderToStaticMarkup(
    <AdminTaskBody
      task={task as Exclude<AdminTask, { kind: "idle" }>}
      titleId="title"
      {...actions}
    />,
  );
};

const listed: AdminEvent = { type: "loaded", accounts: [lead, otter] };

function rows(markup: string): string[] {
  const body = markup.match(/<tbody>(.*?)<\/tbody>/)?.[1] ?? "";
  return [...body.matchAll(/<tr\b[^>]*>(.*?)<\/tr>/g)].map(([, row]) =>
    text(row ?? ""),
  );
}

test("the admin page counts and lists each user account with its avatar, and marks the admins", () => {
  const markup = view(after(listed));

  const [first, second] = rows(markup);
  assert.match(markup, /<h1[^>]*>User accounts<\/h1>/);
  assert.match(text(markup), /2 user accounts/);
  assert.match(
    text(view(after({ type: "loaded", accounts: [lead] }))),
    /1 user account(?!s)/,
  );
  assert.match(control(markup, "Add new user"), /type="button"/);
  assert.doesNotMatch(markup, /type="checkbox"/);
  assert.match(first ?? "", /^WLworkshop-leadAdmin/);
  assert.doesNotMatch(markup, /You/);
  assert.match(second ?? "", /^COcurious-otter/);
  assert.doesNotMatch(second ?? "", /Admin/);
  assert.match(markup, /aria-label="Reset password of curious-otter"/);
  assert.match(markup, /aria-label="Reset password of workshop-lead"/);
});

test("the initials of a username are the first letters of its first two parts", () => {
  assert.equal(initials("curious-otter"), "CO");
  assert.equal(initials("admin"), "A");
  assert.equal(initials("workshop-lead-two"), "WL");
});

test("an empty list says so", () => {
  const markup = view(after({ type: "loaded", accounts: [] }));

  assert.match(text(markup), /No user accounts yet./);
  assert.doesNotMatch(markup, /<table/);
});

test("a list that fails to load shows why", () => {
  const markup = view(
    after({ type: "load-failed", message: "Couldn't reach the METIS API." }),
  );

  assert.match(
    markup,
    /<p role="alert"[^>]*>Couldn&#x27;t reach the METIS API.<\/p>/,
  );
});

test("the table shows the same rows while each dialog is open", () => {
  const tasks: AdminTask[] = [
    { kind: "create-form", admin: false, error: "Try again." },
    { kind: "creating", admin: true },
    { kind: "create-result", account: { ...otter, password } },
    { kind: "confirm-reset", username: "curious-otter" },
    { kind: "resetting", username: "curious-otter" },
    { kind: "reset-result", account: { ...otter, password } },
    { kind: "confirm-delete", username: "curious-otter" },
    { kind: "deleting", username: "curious-otter" },
  ];
  const idle = view(after(listed));

  for (const task of tasks) {
    const markup = view({ ...after(listed), task });
    assert.deepEqual(rows(markup), rows(idle), task.kind);
    assert.doesNotMatch(text(markup), new RegExp(password), task.kind);
    assert.doesNotMatch(markup, /role="alert"/, task.kind);
  }
});

test("a new user account is a Participant unless the admin chooses Admin", () => {
  const form = after(listed, { type: "open-create" });
  assert.deepEqual(form.task, { kind: "create-form", admin: false });
  const markup = dialog(form.task);
  const radio = (label: string) =>
    markup.match(
      new RegExp(`<input type="radio"[^>]*value="${label}"[^>]*>`),
    )?.[0] ?? "";

  assert.match(markup, /<h2[^>]*>Add new user<\/h2>/);
  assert.match(text(markup), /METIS makes the username and the password./);
  assert.match(radio("Participant"), /checked=""/);
  assert.doesNotMatch(radio("Admin"), /checked=""/);
  assert.match(text(markup), /Can also manage all user accounts./);
  assert.match(control(markup, "Cancel"), /type="button"/);
  assert.match(control(markup, "Create"), /type="submit"(?![^>]*disabled)/);

  const creating = adminReducer(
    adminReducer(form, { type: "choose", admin: true }),
    { type: "create" },
  );
  assert.deepEqual(creating.task, { kind: "creating", admin: true });
  assert.match(control(dialog(creating.task), "Create"), /disabled=""/);
  assert.equal(adminReducer(creating, { type: "close" }), creating);

  const failed = adminReducer(creating, {
    type: "failed",
    message: "Only an admin can manage the user accounts.",
  });
  assert.match(
    dialog(failed.task),
    /<p role="alert"[^>]*>Only an admin can manage the user accounts.<\/p>/,
  );
  assert.match(
    dialog(failed.task).match(
      /<input type="radio"[^>]*value="Admin"[^>]*>/,
    )?.[0] ?? "",
    /checked=""/,
  );
});

test("a created user account shows its details once, with one copy text", () => {
  const account = { ...otter, admin: true, password };
  const made = after(
    listed,
    { type: "open-create" },
    { type: "create" },
    { type: "created", account },
  );
  const markup = dialog(made.task);

  assert.match(markup, /<h2[^>]*>User account created<\/h2>/);
  assert.match(
    text(markup),
    /Copy these details and send them to the person as they are. You will not see the password again./,
  );
  assert.match(text(markup), /curious-otter/);
  assert.match(text(markup), new RegExp(password));
  assert.ok(control(markup, "Copy"));
  assert.ok(control(markup, "Done"));
  assert.equal(
    credentialsText(account),
    `Username: curious-otter\nPassword: ${password}`,
  );
  assert.match(rows(view(made)).at(-1) ?? "", /^COcurious-otterAdmin/);

  const done = adminReducer(made, { type: "close" });
  assert.deepEqual(done.task, { kind: "idle" });
  assert.doesNotMatch(JSON.stringify(done), new RegExp(password));
});

test("a password reset asks first, then shows the new password once", () => {
  const asked = after(listed, { type: "ask-reset", username: "curious-otter" });
  assert.match(
    text(dialog(asked.task)),
    /Reset the password of curious-otter\? curious-otter is logged out, and the old password stops working./,
  );
  assert.ok(control(dialog(asked.task), "Reset password"));
  assert.deepEqual(adminReducer(asked, { type: "close" }), after(listed));

  const resetting = adminReducer(asked, { type: "reset" });
  assert.match(
    control(dialog(resetting.task), "Reset password"),
    /disabled=""/,
  );

  const reset = adminReducer(resetting, {
    type: "reset-done",
    account: { ...otter, password },
  });
  const markup = dialog(reset.task);
  assert.match(markup, /<h2[^>]*>New password for curious-otter<\/h2>/);
  assert.match(markup, new RegExp(`<span class="sr-only">${password}</span>`));
  assert.ok(control(markup, "Copy"));
  assert.deepEqual(reset.load, after(listed).load);

  const done = adminReducer(reset, { type: "close" });
  assert.deepEqual(done, after(listed));
});

test("a delete asks first, then removes the row of the user account", () => {
  const markup = view(after(listed));

  assert.match(markup, /aria-label="Delete curious-otter"/);
  assert.doesNotMatch(markup, /aria-label="Delete workshop-lead"/);
  assert.match(view(after(listed), null), /aria-label="Delete workshop-lead"/);

  const asked = after(listed, {
    type: "ask-delete",
    username: "curious-otter",
  });
  assert.match(text(dialog(asked.task)), /You cannot undo this./);
  assert.deepEqual(adminReducer(asked, { type: "close" }), after(listed));

  const deleting = adminReducer(asked, { type: "delete" });
  assert.match(
    control(dialog(deleting.task), "Delete user account"),
    /disabled=""/,
  );
  const failed = adminReducer(deleting, {
    type: "failed",
    message: "Stop the run, then try again.",
  });
  assert.match(dialog(failed.task), /role="alert"[^>]*>Stop the run/);

  const deleted = adminReducer(deleting, {
    type: "deleted",
    username: "curious-otter",
  });
  assert.deepEqual(deleted, after({ type: "loaded", accounts: [lead] }));
});

const session = (user: UserAccount) => ({
  user,
  logout: () => {},
  workshopEnv: null,
});

test("only an admin sees the admin page", () => {
  const fallback = <p>This page does not exist.</p>;
  const page = (user: UserAccount | null) =>
    renderToStaticMarkup(
      <LoginSessionProvider value={user ? session(user) : null}>
        <Router ssrPath="/admin">
          <AdminRoute fallback={fallback} />
          <TargetRail
            targets={[]}
            problems={[]}
            selectedId={null}
            activeIds={new Set()}
            onNew={() => {}}
            onDelete={() => {}}
          />
        </Router>
      </LoginSessionProvider>,
    );

  const admin = page(lead);
  assert.match(admin, /<h1[^>]*>User accounts<\/h1>/);
  assert.doesNotMatch(admin, /aria-current/);

  for (const markup of [page(otter), page(null)]) {
    assert.match(markup, /This page does not exist./);
    assert.doesNotMatch(markup, /User accounts/);
    assert.doesNotMatch(markup, /href="\/admin"/);
  }
});
