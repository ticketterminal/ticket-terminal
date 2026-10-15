import { apiJson } from "./api.js";
import { el } from "./dom-utils.js";

const REFRESH_MS = 30000;

function dateLabel(value){
  if (!value) return "";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

export function createTicketCommentsView(key, data){
  const tracker = data.source === "notion" ? "Notion" : "Jira";
  const shell = el("section", "trackercomments");
  const heading = el("div", "trackercomments-head");
  heading.appendChild(el("span", "reflabel", tracker + " comments"));
  const refresh = el("button", "trackercomments-refresh", "Refresh");
  refresh.type = "button";
  refresh.title = "Fetch the latest comments from " + tracker;
  heading.appendChild(refresh);
  shell.appendChild(heading);

  const status = el("span", "trackercomments-status");
  status.setAttribute("aria-live", "polite");
  const list = el("div", "trackercomments-list");
  shell.appendChild(status);
  shell.appendChild(list);

  let comments = [];
  let timer = null;
  let active = false;
  let loading = false;

  function setStatus(message, error=false){
    status.textContent = message || "";
    status.classList.toggle("error", error);
  }

  function render(){
    list.replaceChildren();
    if (!comments.length){
      list.appendChild(el("span", "empty", "No comments yet."));
      return;
    }
    comments.forEach(comment => {
      const card = el("article", "trackercomment");
      const meta = el("div", "trackercomment-meta");
      meta.appendChild(el("strong", "trackercomment-author", comment.author || tracker + " user"));
      meta.appendChild(el("time", "trackercomment-time", dateLabel(comment.updatedAt || comment.createdAt)));
      if (comment.editable){
        const edit = el("button", "trackercomment-edit", "Edit");
        edit.type = "button";
        edit.addEventListener("click", () => showEditor(card, comment));
        meta.appendChild(edit);
      }
      card.appendChild(meta);
      card.appendChild(el("div", "trackercomment-body", comment.body || ""));
      list.appendChild(card);
    });
  }

  function showEditor(card, comment){
    const original = card.querySelector(".trackercomment-body");
    const metaEdit = card.querySelector(".trackercomment-edit");
    const form = document.createElement("form");
    form.className = "trackercomment-editor";
    const input = document.createElement("textarea");
    input.value = comment.body || "";
    input.rows = 3;
    input.maxLength = 32767;
    input.setAttribute("aria-label", "Edit comment");
    const actions = el("div", "trackercomment-actions");
    const save = el("button", "trackercomment-save", "Save");
    save.type = "submit";
    const cancel = el("button", "trackercomment-cancel", "Cancel");
    cancel.type = "button";
    actions.appendChild(save); actions.appendChild(cancel);
    form.appendChild(input); form.appendChild(actions);
    original.replaceWith(form);
    metaEdit.hidden = true;
    input.focus?.();
    cancel.addEventListener("click", render);
    form.addEventListener("submit", async event => {
      event.preventDefault();
      const text = input.value.trim();
      if (!text) return;
      save.disabled = true;
      setStatus("Saving to " + tracker + "…");
      try {
        const result = await apiJson("/api/tickets/" + encodeURIComponent(key) + "/comments/" + encodeURIComponent(comment.id), {
          method:"PATCH", body:JSON.stringify({text}),
        });
        if (!result.ok) throw new Error(result.error || "Could not update comment");
        comments = comments.map(item => item.id === comment.id ? result.comment : item);
        setStatus("Saved to " + tracker + ".");
        render();
      } catch (error) {
        save.disabled = false;
        setStatus(error.message, true);
      }
    });
  }

  async function load({quiet=false}={}){
    if (data.isDemo || loading) return;
    loading = true;
    refresh.disabled = true;
    if (!quiet) setStatus("Loading from " + tracker + "…");
    try {
      const result = await apiJson("/api/tickets/" + encodeURIComponent(key) + "/comments");
      if (!result.ok) throw new Error(result.error || "Could not load comments");
      comments = Array.isArray(result.comments) ? result.comments : [];
      setStatus("");
      render();
    } catch (error) {
      setStatus(error.message, true);
      if (!comments.length) list.replaceChildren(el("span", "empty", "Comments unavailable."));
    } finally {
      loading = false;
      refresh.disabled = false;
    }
  }

  refresh.addEventListener("click", () => load());

  const form = document.createElement("form");
  form.className = "trackercomment-add";
  const input = document.createElement("textarea");
  input.rows = 2;
  input.maxLength = 32767;
  input.placeholder = "Add a comment to " + tracker + "…";
  input.setAttribute("aria-label", "New " + tracker + " comment");
  const add = el("button", null, "Add comment");
  add.type = "submit";
  form.appendChild(input); form.appendChild(add);
  shell.appendChild(form);
  form.addEventListener("submit", async event => {
    event.preventDefault();
    const text = input.value.trim();
    if (!text) return;
    add.disabled = true;
    setStatus("Adding to " + tracker + "…");
    try {
      const result = await apiJson("/api/tickets/" + encodeURIComponent(key) + "/comments", {
        method:"POST", body:JSON.stringify({text}),
      });
      if (!result.ok) throw new Error(result.error || "Could not add comment");
      input.value = "";
      comments.push(result.comment);
      setStatus("Added to " + tracker + ".");
      render();
    } catch (error) {
      setStatus(error.message, true);
    } finally { add.disabled = false; }
  });

  if (data.isDemo){
    refresh.disabled = true; input.disabled = true; add.disabled = true;
    input.placeholder = "Demo ticket — tracker comments aren't available";
    list.appendChild(el("span", "empty", "Connect a real Jira or Notion ticket to view comments."));
  }

  return {
    shell,
    start(){
      if (active || data.isDemo) return;
      active = true;
      load();
      timer = setInterval(() => {
        if (!shell.isConnected){ clearInterval(timer); timer = null; active = false; return; }
        load({quiet:true});
      }, REFRESH_MS);
      timer.unref?.(); // lets DOM-only Node tests exit; browser interval ids are numbers
    },
    stop(){ active = false; clearInterval(timer); timer = null; },
    dispose(){ active = false; clearInterval(timer); timer = null; },
  };
}
