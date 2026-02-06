// Demonstrate blocked access and path traversal in the isolate.
console.log("process is", typeof process);
console.log("require is", typeof require);

try {
  writeFile("../escape.txt", "should not write outside out_dir\n");
} catch (err) {
  console.log("blocked traversal:", String(err));
}

try {
  for (let i = 0; i < 200; i += 1) {
    writeFile(`file-${i}.txt`, "x");
  }
} catch (err) {
  console.log("blocked output quota:", String(err));
}
