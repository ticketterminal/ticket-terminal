/* ---- local REST/WebSocket shim, standing in for the old Artifact `db`
   capability. Mimics just enough of its doc()/collection() shape (used
   throughout the board) that none of the rendering/mutation code needed to
   change when this stopped being an Artifact — only this adapter and init()
   are new. No realtime push (single local user, no need for it): every
   mutation just re-fetches and re-renders. */
import { reloadBoard } from "./polling.js";
import { state } from "./state.js";

export function makeSnapshot(id, data){ return { id, data: () => data }; }

/* The single place `?w=<slug>` is added: every REST call the board makes goes
   through apiJson, so no call site needs to know workspaces exist. An empty
   state.workspaceSlug (a bare route, i.e. the default workspace) sends nothing,
   which is exactly the request a one-workspace install always made. Some paths
   already carry a query string (/api/categories?revision=…), hence the & case. */
export function withWorkspace(path){
  if (!state.workspaceSlug) return path;
  return path + (path.includes("?") ? "&" : "?") + "w=" + encodeURIComponent(state.workspaceSlug);
}

export async function apiJson(path, opts){
  const res = await fetch(withWorkspace(path), Object.assign({headers:{"Content-Type":"application/json"}}, opts || {}));
  if (!res.ok) throw new Error("Request failed: " + path);
  return res.status === 204 ? null : res.json();
}

export const localDb = {
  doc(path){
    const parts = path.split("/");
    const collection = parts[0];
    const docId = parts.slice(1).join("/");
    return {
      async update(patch){
        if (collection === "jiraTickets") await apiJson("/api/tickets/" + encodeURIComponent(docId), {method:"PATCH", body: JSON.stringify(patch)});
        await reloadBoard();
      },
      async set(data){
        if (collection === "people") await apiJson("/api/people/" + encodeURIComponent(docId), {method:"PUT", body: JSON.stringify(data)});
        else if (collection === "meta" && docId === "teamOptions") await apiJson("/api/team-options", {method:"PUT", body: JSON.stringify(data)});
        await reloadBoard();
      }
    };
  },
  collection(name){
    return {
      async get(){
        const obj = await apiJson(name === "jiraTickets" ? "/api/tickets" : "/api/people");
        return { docs: Object.keys(obj).map(k => makeSnapshot(k, obj[k])) };
      }
    };
  }
};

export function touch(dbRef, id, patch){
  if (!dbRef) return;
  dbRef.doc("jiraTickets/"+id).update(Object.assign({updatedAt:new Date().toISOString(), reviewed:true}, patch));
}
