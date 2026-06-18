/** Minimal GOOF v2 decoder (browser end of adalog.bridge_codec). */
const DEC = new TextDecoder();

function readU32LE(b: Uint8Array, o: number) { return (b[o] | (b[o+1]<<8) | (b[o+2]<<16) | (b[o+3]<<24)) >>> 0; }

// Tiny msgpack decoder covering what our headers/meta use (maps, strings, ints, floats, null, bool).
function unpack(b: Uint8Array, o: { i: number }): any {
	const c = b[o.i++];
	if (c < 0x80) return c;                         // positive fixint
	if (c >= 0xe0) return c - 256;                  // negative fixint
	if (c >= 0x80 && c <= 0x8f) return readMap(b, o, c & 0x0f);
	if (c >= 0x90 && c <= 0x9f) return readArr(b, o, c & 0x0f);
	if (c >= 0xa0 && c <= 0xbf) return readStr(b, o, c & 0x1f);
	switch (c) {
		case 0xc0: return null;
		case 0xc2: return false;
		case 0xc3: return true;
		case 0xcc: return b[o.i++];
		case 0xcd: { const v = (b[o.i]<<8)|b[o.i+1]; o.i+=2; return v; }
		case 0xce: { const v = readU32LE_be(b, o.i); o.i+=4; return v; }
		case 0xcf: { let v=0n; for(let k=0;k<8;k++) v=(v<<8n)|BigInt(b[o.i+k]); o.i+=8; return Number(v); }
		case 0xd0: { const v=b[o.i++]; return v<128?v:v-256; }
		case 0xd1: { let v=(b[o.i]<<8)|b[o.i+1]; o.i+=2; return v<32768?v:v-65536; }
		case 0xd2: { const v=readU32LE_be(b,o.i)|0; o.i+=4; return v; }
		case 0xd3: { let v=0n; for(let k=0;k<8;k++) v=(v<<8n)|BigInt(b[o.i+k]); o.i+=8; return Number(BigInt.asIntN(64,v)); }
		case 0xca: { const dv=new DataView(b.buffer,b.byteOffset+o.i,4); o.i+=4; return dv.getFloat32(0,false); }
		case 0xcb: { const dv=new DataView(b.buffer,b.byteOffset+o.i,8); o.i+=8; return dv.getFloat64(0,false); }
		case 0xd9: { const n=b[o.i++]; return readStr(b,o,n); }
		case 0xda: { const n=(b[o.i]<<8)|b[o.i+1]; o.i+=2; return readStr(b,o,n); }
		case 0xde: { const n=(b[o.i]<<8)|b[o.i+1]; o.i+=2; return readMap(b,o,n); }
		case 0xdc: { const n=(b[o.i]<<8)|b[o.i+1]; o.i+=2; return readArr(b,o,n); }
		default: return null;
	}
}
function readU32LE_be(b: Uint8Array, o: number){ return ((b[o]<<24)|(b[o+1]<<16)|(b[o+2]<<8)|b[o+3])>>>0; }
function readStr(b: Uint8Array, o: {i:number}, n: number){ const s=DEC.decode(b.subarray(o.i,o.i+n)); o.i+=n; return s; }
function readMap(b: Uint8Array, o: {i:number}, n: number){ const m:any={}; for(let k=0;k<n;k++){ const key=unpack(b,o); m[key]=unpack(b,o);} return m; }
function readArr(b: Uint8Array, o: {i:number}, n: number){ const a:any[]=[]; for(let k=0;k<n;k++) a.push(unpack(b,o)); return a; }

export function decodeFrame(buf: Uint8Array): { header: any; value: any } {
	// [4-byte BE header length][msgpack header][GOOF frame]
	const hlen = (buf[0]<<24)|(buf[1]<<16)|(buf[2]<<8)|buf[3];
	const header = unpack(buf, { i: 4 });
	const goof = buf.subarray(4 + hlen);
	return { header, value: decodeGoof(goof) };
}

function decodeGoof(b: Uint8Array): any {
	// header: <4sBBII> magic(4) version(1) dtype(1) meta_len(4 LE) body_len(4 LE)
	const dtype = b[5];
	const metaLen = readU32LE(b, 6);
	const bodyOff = 14 + metaLen;
	const body = b.subarray(bodyOff);
	if (dtype === 1) return DEC.decode(body);          // STRING
	if (dtype === 0) return decodeArray(body);          // ARRAY
	return null;
}

function decodeArray(b: Uint8Array): Float32Array | null {
	let i = 0;
	const ndim = b[i++];
	const dlen = b[i++];
	const dstr = DEC.decode(b.subarray(i, i + dlen)); i += dlen;
	const shape: number[] = [];
	for (let d = 0; d < ndim; d++) { let v=0n; for(let k=0;k<8;k++) v=(v<<8n)|BigInt(b[i+k]); i+=8; shape.push(Number(v)); }
	// Copy the body into a fresh, offset-0 buffer before viewing it as a typed array:
	// raw.byteOffset depends on the variable-length msgpack header, so it is almost never
	// 4/8-byte aligned, and Float32Array/Float64Array views REQUIRE an aligned byteOffset
	// (else RangeError). slice() gives a new buffer whose data starts at offset 0.
	const raw = b.slice(i);
	if (dstr.includes('f4')) return new Float32Array(raw.buffer, 0, raw.byteLength >> 2);
	if (dstr.includes('f8')) return Float32Array.from(new Float64Array(raw.buffer, 0, raw.byteLength >> 3));
	return null;
}
