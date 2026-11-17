@0xd4f6a2c1b3e5f701;

interface Sink {
  frame @0 (data :Data, index :UInt32) -> ();
  done @1 (status :Text) -> ();
}

interface Op {
  cancel @0 () -> ();
}

interface Spike {
  hello @0 (agentId :Text, token :Data) -> (sessionId :Text, peerSan :Text);
  stream @1 (rows :UInt32, maxFrameBytes :UInt32, sink :Sink) -> (op :Op);
}
