// AlumniConnect core engine.
// Reads ONE JSON request from stdin, writes ONE JSON response to stdout.
// Data structures: dynamic array, insertion sort, binary search, doubly linked list,
// array-based priority queue, circular queue, stack.
#include <iostream>
#include <sstream>
#include <string>
#include <vector>
#include <map>
#include <cstdlib>
#include <cctype>
#include <cstring>
using namespace std;

// ---------------- minimal JSON ----------------
struct J {
    enum T { NUL, NUM, STR, ARR, OBJ, BOOL } t = NUL;
    double n = 0; string s; bool b = false;
    vector<J> a; map<string, J> o;
    const J& at(const string& k) const { static J nul; auto i = o.find(k); return i == o.end() ? nul : i->second; }
    string str() const { if (t == STR) return s; if (t == NUM) { ostringstream x; x << (long long)n; return x.str(); } return ""; }
    long long num() const { return t == NUM ? (long long)n : (t == STR ? atoll(s.c_str()) : 0); }
};
struct P {
    const string& s; size_t i = 0;
    P(const string& x) : s(x) {}
    void ws() { while (i < s.size() && isspace((unsigned char)s[i])) i++; }
    J val() {
        ws(); J v;
        if (i >= s.size()) return v;
        char c = s[i];
        if (c == '{') { i++; v.t = J::OBJ; ws(); if (s[i] == '}') { i++; return v; }
            while (true) { ws(); string k = str(); ws(); i++; v.o[k] = val(); ws(); if (s[i] == ',') { i++; continue; } i++; break; } }
        else if (c == '[') { i++; v.t = J::ARR; ws(); if (s[i] == ']') { i++; return v; }
            while (true) { v.a.push_back(val()); ws(); if (s[i] == ',') { i++; continue; } i++; break; } }
        else if (c == '"') { v.t = J::STR; v.s = str(); }
        else if (s.compare(i, 4, "true") == 0) { v.t = J::BOOL; v.b = true; i += 4; }
        else if (s.compare(i, 5, "false") == 0) { v.t = J::BOOL; i += 5; }
        else if (s.compare(i, 4, "null") == 0) { i += 4; }
        else { size_t st = i; while (i < s.size() && (isdigit((unsigned char)s[i]) || strchr("+-.eE", s[i]))) i++; v.t = J::NUM; v.n = atof(s.substr(st, i - st).c_str()); }
        return v;
    }
    string str() {
        string r; i++;
        while (i < s.size() && s[i] != '"') {
            if (s[i] == '\\') { i++; char e = s[i];
                if (e == 'n') r += '\n'; else if (e == 't') r += '\t';
                else if (e == 'u') { r += '?'; i += 4; } else r += e; }
            else r += s[i];
            i++;
        }
        i++; return r;
    }
};
string esc(const string& x) { string r; for (char c : x) { if (c == '"' || c == '\\') { r += '\\'; r += c; } else if (c == '\n') r += "\\n"; else r += c; } return r; }

// ---------------- records (array) ----------------
struct Rec { long long id; string prn; long long year; string status; double priority; };
vector<Rec> load(const J& req) {
    vector<Rec> v;
    for (const J& r : req.at("records").a)
        v.push_back({r.at("id").num(), r.at("prn").str(), r.at("graduation_year").num(), r.at("status").str(), r.at("priority").n});
    return v;
}
string ids(const vector<long long>& v) { string r = "["; for (size_t i = 0; i < v.size(); i++) { if (i) r += ","; r += to_string(v[i]); } return r + "]"; }

// ---------------- insertion sort ----------------
int statusRank(const string& s) { return s == "PENDING" ? 0 : s == "COMPLETED" ? 2 : 1; }
void sortRecs(vector<Rec>& a, const string& key) {
    auto before = [&](const Rec& x, const Rec& y) {
        if (key == "graduation_year") return x.year < y.year;
        if (key == "status") return statusRank(x.status) < statusRank(y.status);
        if (key == "priority") return x.priority > y.priority;
        return x.prn < y.prn;
    };
    for (size_t i = 1; i < a.size(); i++) {
        Rec current = a[i];
        int j = (int)i - 1;
        while (j >= 0 && before(current, a[j])) {
            a[j + 1] = a[j];
            j--;
        }
        a[j + 1] = current;
    }
}

// ---------------- doubly linked list ----------------
struct Node { long long id; Node *prev = nullptr, *next = nullptr; };
struct DList {
    Node *head = nullptr, *tail = nullptr; int size = 0;
    void push_back(long long id) { Node* n = new Node{id}; if (!tail) head = tail = n; else { tail->next = n; n->prev = tail; tail = n; } size++; }
    bool remove(long long id) {
        for (Node* n = head; n; n = n->next) if (n->id == id) {
            if (n->prev) n->prev->next = n->next; else head = n->next;
            if (n->next) n->next->prev = n->prev; else tail = n->prev;
            delete n; size--; return true; }
        return false;
    }
    vector<long long> forward() { vector<long long> v; for (Node* n = head; n; n = n->next) v.push_back(n->id); return v; }
    ~DList() { while (head) { Node* n = head->next; delete head; head = n; } }
};

// ---------------- array-based priority queue ----------------
// Highest priority is removed first. This uses a simple array-based
// implementation of the Priority Queue ADT (not a binary heap).
struct PQ {
    vector<Rec> items;
    static bool before(const Rec& a, const Rec& b) {
        return a.priority > b.priority || (a.priority == b.priority && a.id < b.id);
    }
    void push(const Rec& r) { items.push_back(r); }
    Rec pop() {
        size_t best = 0;
        for (size_t i = 1; i < items.size(); i++)
            if (before(items[i], items[best])) best = i;
        Rec top = items[best];
        items.erase(items.begin() + best);
        return top;
    }
    bool empty() const { return items.empty(); }
};

// ---------------- circular queue ----------------
struct CQ {
    vector<long long> buf; int head = 0, count = 0;
    CQ(int cap) : buf(cap) {}
    bool full() const { return count == (int)buf.size(); }
    bool empty() const { return count == 0; }
    void enqueue(long long x) { buf[(head + count) % buf.size()] = x; count++; }
    long long dequeue() { long long x = buf[head]; head = (head + 1) % buf.size(); count--; return x; }
};

// ---------------- stack ----------------
struct Stack { vector<long long> a; void push(long long x) { a.push_back(x); } long long pop() { long long x = a.back(); a.pop_back(); return x; } bool empty() const { return a.empty(); } };

int main() {
    string in((istreambuf_iterator<char>(cin)), istreambuf_iterator<char>());
    P p(in); J req = p.val();
    string cmd = req.at("cmd").str();

    if (cmd == "search") {                       // exact PRN lookup
        vector<Rec> a = load(req); sortRecs(a, "prn");
        string q = req.at("prn").str(); int lo = 0, hi = (int)a.size() - 1;
        while (lo <= hi) { int m = (lo + hi) / 2;
            if (a[m].prn == q) { cout << "{\"found\":true,\"id\":" << a[m].id << "}"; return 0; }
            if (a[m].prn < q) lo = m + 1; else hi = m - 1; }
        cout << "{\"found\":false,\"id\":null}";
    } else if (cmd == "sort") {
        vector<Rec> a = load(req); sortRecs(a, req.at("key").str());
        vector<long long> v; for (auto& r : a) v.push_back(r.id);
        cout << "{\"ids\":" << ids(v) << "}";
    } else if (cmd == "pending_list") {          // doubly linked list of pending alumni
        DList l; vector<Rec> a = load(req);
        for (auto& r : a) if (r.status == "PENDING") l.push_back(r.id);
        for (const J& x : req.at("remove").a) l.remove(x.num());
        cout << "{\"ids\":" << ids(l.forward()) << ",\"size\":" << l.size << "}";
    } else if (cmd == "schedule") {              // priority queue -> circular queue batches
        vector<Rec> a = load(req); int bs = (int)req.at("batch_size").num(); if (bs < 1) bs = 10;
        PQ pq; for (auto& r : a) pq.push(r);
        CQ cq(bs); vector<long long> order; string batches = "[";
        bool first = true;
        while (!pq.empty() || !cq.empty()) {
            while (!pq.empty() && !cq.full()) cq.enqueue(pq.pop().id);
            vector<long long> b; while (!cq.empty()) b.push_back(cq.dequeue());
            for (auto x : b) order.push_back(x);
            batches += (first ? "" : ",") + ids(b); first = false;
        }
        cout << "{\"order\":" << ids(order) << ",\"batches\":" << batches << "]}";
    } else if (cmd == "undo") {                  // actions oldest -> newest; pop the newest
        Stack s; for (const J& x : req.at("actions").a) s.push(x.num());
        if (s.empty()) cout << "{\"action_id\":null,\"remaining\":0}";
        else { long long t = s.pop(); cout << "{\"action_id\":" << t << ",\"remaining\":" << s.a.size() << "}"; }
    } else {
        cout << "{\"error\":\"unknown command\"}"; return 1;
    }
    return 0;
}
