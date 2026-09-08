(* Optional lifecycle verifier.
   Input format: one transition per line, for example:
     INSTALLED STARTING
     STARTING RUNNING
   The tool is standard-library-only and independent of the Rust host. *)

module State = struct
  type t =
    | Installed | Starting | Running | Stopping | Stopped | Failed
    | Restarting | Updating | Deleting | Quarantined

  let of_string = function
    | "INSTALLED" -> Installed | "STARTING" -> Starting | "RUNNING" -> Running
    | "STOPPING" -> Stopping | "STOPPED" -> Stopped | "FAILED" -> Failed
    | "RESTARTING" -> Restarting | "UPDATING" -> Updating
    | "DELETING" -> Deleting | "QUARANTINED" -> Quarantined
    | value -> invalid_arg ("unknown state: " ^ value)

  let allowed from_state to_state =
    match from_state, to_state with
    | Installed, (Starting | Deleting | Updating | Quarantined)
    | Starting, (Running | Failed | Stopping | Quarantined)
    | Running, (Stopping | Restarting | Failed | Updating | Quarantined)
    | Stopping, (Stopped | Failed)
    | Stopped, (Starting | Deleting | Updating | Quarantined)
    | Failed, (Restarting | Stopping | Quarantined | Deleting)
    | Restarting, (Starting | Running | Failed | Quarantined)
    | Updating, (Running | Stopped | Failed)
    | Quarantined, (Starting | Deleting | Stopped) -> true
    | _ when from_state = to_state -> true
    | _ -> false
end

let verify_line line number =
  match String.split_on_char ' ' (String.trim line) |> List.filter ((<>) "") with
  | [] -> true
  | [from_state; to_state] ->
      let valid = State.allowed (State.of_string from_state) (State.of_string to_state) in
      if not valid then Printf.eprintf "line %d: invalid transition %s -> %s\n" number from_state to_state;
      valid
  | _ -> Printf.eprintf "line %d: expected FROM TO\n" number; false

let () =
  let input = if Array.length Sys.argv > 1 then open_in Sys.argv.(1) else stdin in
  let valid = ref true in
  (try
     let line = ref 1 in
     while true do
       valid := verify_line (input_line input) !line && !valid;
       incr line
     done
   with End_of_file -> ());
  if input != stdin then close_in input;
  if !valid then print_endline "lifecycle transitions: valid" else exit 1
