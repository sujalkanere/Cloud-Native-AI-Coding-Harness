//! High-performance Rust execution runner and stream multiplexer for Cloud-Native AI Coding Harness.
//! Executes commands inside Linux sandboxes, streams stdout/stderr asynchronously line-by-line,
//! and ensures sub-second signal termination.

use chrono::Utc;
use serde::{Deserialize, Serialize};
use std::env;
use std::process::Stdio;
use std::time::Duration;
use tokio::io::{AsyncBufReadExt, BufReader};
use tokio::process::Command;
use tokio::time::timeout;

#[derive(Serialize, Deserialize, Debug)]
pub struct ExecEvent {
    pub stream: String,
    pub data: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub exit_code: Option<i32>,
    pub timestamp: String,
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<String> = env::args().collect();
    if args.len() < 2 {
        eprintln!("Usage: harness-runner <command> [cwd] [timeout_secs]");
        std::process::exit(1);
    }

    let command_str = &args[1];
    let cwd = if args.len() > 2 { &args[2] } else { "/workspace" };
    let timeout_secs: u64 = if args.len() > 3 {
        args[3].parse().unwrap_or(60)
    } else {
        60
    };

    let mut cmd = Command::new("sh");
    cmd.arg("-c")
        .arg(command_str)
        .current_dir(cwd)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());

    let mut child = match cmd.spawn() {
        Ok(child) => child,
        Err(err) => {
            let ev = ExecEvent {
                stream: "stderr".to_string(),
                data: format!("Failed to spawn command: {}\n", err),
                exit_code: Some(1),
                timestamp: Utc::now().to_rfc3339(),
            };
            println!("{}", serde_json::to_string(&ev).unwrap());
            std::process::exit(1);
        }
    };

    let stdout = child.stdout.take().expect("Child did not have a stdout handle");
    let stderr = child.stderr.take().expect("Child did not have a stderr handle");

    let mut stdout_reader = BufReader::new(stdout).lines();
    let mut stderr_reader = BufReader::new(stderr).lines();

    let stdout_task = tokio::spawn(async move {
        while let Ok(Some(line)) = stdout_reader.next_line().await {
            let ev = ExecEvent {
                stream: "stdout".to_string(),
                data: format!("{}\n", line),
                exit_code: None,
                timestamp: Utc::now().to_rfc3339(),
            };
            println!("{}", serde_json::to_string(&ev).unwrap());
        }
    });

    let stderr_task = tokio::spawn(async move {
        while let Ok(Some(line)) = stderr_reader.next_line().await {
            let ev = ExecEvent {
                stream: "stderr".to_string(),
                data: format!("{}\n", line),
                exit_code: None,
                timestamp: Utc::now().to_rfc3339(),
            };
            println!("{}", serde_json::to_string(&ev).unwrap());
        }
    });

    let wait_res = timeout(Duration::from_secs(timeout_secs), child.wait()).await;

    let exit_code = match wait_res {
        Ok(Ok(status)) => status.code().unwrap_or(1),
        Ok(Err(err)) => {
            eprintln!("Wait error: {}", err);
            1
        }
        Err(_) => {
            let _ = child.kill().await;
            let ev = ExecEvent {
                stream: "stderr".to_string(),
                data: format!("Command timed out after {} seconds\n", timeout_secs),
                exit_code: Some(124),
                timestamp: Utc::now().to_rfc3339(),
            };
            println!("{}", serde_json::to_string(&ev).unwrap());
            124
        }
    };

    let _ = tokio::join!(stdout_task, stderr_task);

    let exit_ev = ExecEvent {
        stream: "exit".to_string(),
        data: String::new(),
        exit_code: Some(exit_code),
        timestamp: Utc::now().to_rfc3339(),
    };
    println!("{}", serde_json::to_string(&exit_ev).unwrap());

    std::process::exit(exit_code);
}
