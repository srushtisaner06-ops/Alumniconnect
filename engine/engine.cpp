// AlumniConnect core engine.
// Reads ONE JSON request from stdin, writes ONE JSON response to stdout.
// Data structures: custom dynamic array, insertion sort, binary search,
// doubly linked list, array-based priority queue, circular queue, stack.
#include <iostream>
#include <sstream>
#include <string>
#include <map>
#include <cstdlib>
#include <cctype>
#include <cstring>
#include <iterator>
#include <utility>
using namespace std;

// ---------------- manually implemented dynamic array ----------------
template <typename T>
class DynamicArray {
    T* data;
    size_t length;
    size_t capacity;

    void grow(size_t minimum) {
        size_t newCapacity = capacity == 0 ? 4 : capacity * 2;
        while (newCapacity < minimum) newCapacity *= 2;
        T* next = new T[newCapacity]();
        for (size_t i = 0; i < length; ++i) next[i] = data[i];
        delete[] data;
        data = next;
        capacity = newCapacity;
    }

public:
    DynamicArray() : data(nullptr), length(0), capacity(0) {}

    // Creates an array with 'count' value-initialized elements (used by CQ).
    explicit DynamicArray(size_t count)
        : data(count ? new T[count]() : nullptr), length(count), capacity(count) {}

    DynamicArray(const DynamicArray& other)
        : data(other.length ? new T[other.length] : nullptr),
          length(other.length), capacity(other.length) {
        for (size_t i = 0; i < length; ++i) data[i] = other.data[i];
    }

    DynamicArray(DynamicArray&& other) noexcept
        : data(other.data), length(other.length), capacity(other.capacity) {
        other.data = nullptr;
        other.length = other.capacity = 0;
    }

    DynamicArray& operator=(const DynamicArray& other) {
        if (this != &other) {
            T* next = other.length ? new T[other.length] : nullptr;
            for (size_t i = 0; i < other.length; ++i) next[i] = other.data[i];
            delete[] data;
            data = next;
            length = capacity = other.length;
        }
        return *this;
    }

    DynamicArray& operator=(DynamicArray&& other) noexcept {
        if (this != &other) {
            delete[] data;
            data = other.data;
            length = other.length;
            capacity = other.capacity;
            other.data = nullptr;
            other.length = other.capacity = 0;
        }
        return *this;
    }

    ~DynamicArray() { delete[] data; }

    void push_back(const T& value) {
        if (length == capacity) grow(length + 1);
        data[length++] = value;
    }

    void pop_back() { if (length > 0) --length; }
    T& back() { return data[length - 1]; }
    const T& back() const { return data[length - 1]; }

    void erase(size_t index) {
        if (index >= length) return;
        for (size_t i = index; i + 1 < length; ++i) data[i] = data[i + 1];
        --length;
    }

    size_t size() const { return length; }
    bool empty() const { return length == 0; }
    T& operator[](size_t index) { return data[index]; }
    const T& operator[](size_t index) const { return data[index]; }
};

// ---------------- minimal JSON ----------------
struct J {
    enum T { NUL, NUM, STR, ARR, OBJ, BOOL } t = NUL;
    double n = 0;
    string s;
    bool b = false;
    DynamicArray<J> a;
    map<string, J> o;

    const J& at(const string& k) const {
        static J nul;
        auto i = o.find(k);
        return i == o.end() ? nul : i->second;
    }
    string str() const {
        if (t == STR) return s;
        if (t == NUM) { ostringstream x; x << (long long)n; return x.str(); }
        return "";
    }
    long long num() const {
        return t == NUM ? (long long)n : (t == STR ? atoll(s.c_str()) : 0);
    }
};

struct P {
    const string& s;
    size_t i = 0;
    P(const string& x) : s(x) {}
    void ws() { while (i < s.size() && isspace((unsigned char)s[i])) i++; }

    J val() {
        ws(); J v;
        if (i >= s.size()) return v;
        char c = s[i];
        if (c == '{') {
            i++; v.t = J::OBJ; ws();
            if (i < s.size() && s[i] == '}') { i++; return v; }
            while (i < s.size()) {
                ws(); string k = str(); ws();
                if (i < s.size()) ++i; // colon
                v.o[k] = val(); ws();
                if (i < s.size() && s[i] == ',') { i++; continue; }
                if (i < s.size()) ++i; // closing brace
                break;
            }
        } else if (c == '[') {
            i++; v.t = J::ARR; ws();
            if (i < s.size() && s[i] == ']') { i++; return v; }
            while (i < s.size()) {
                v.a.push_back(val()); ws();
                if (i < s.size() && s[i] == ',') { i++; continue; }
                if (i < s.size()) ++i; // closing bracket
                break;
            }
        } else if (c == '"') {
            v.t = J::STR; v.s = str();
        } else if (s.compare(i, 4, "true") == 0) {
            v.t = J::BOOL; v.b = true; i += 4;
        } else if (s.compare(i, 5, "false") == 0) {
            v.t = J::BOOL; i += 5;
        } else if (s.compare(i, 4, "null") == 0) {
            i += 4;
        } else {
            size_t st = i;
            while (i < s.size() && (isdigit((unsigned char)s[i]) || strchr("+-.eE", s[i]))) i++;
            v.t = J::NUM; v.n = atof(s.substr(st, i - st).c_str());
        }
        return v;
    }

    string str() {
        string r;
        if (i < s.size() && s[i] == '"') ++i;
        while (i < s.size() && s[i] != '"') {
            if (s[i] == '\\') {
                ++i;
                if (i >= s.size()) break;
                char e = s[i];
                if (e == 'n') r += '\n';
                else if (e == 't') r += '\t';
                else if (e == 'r') r += '\r';
                else if (e == 'u') { r += '?'; i += 4; }
                else r += e;
            } else r += s[i];
            ++i;
        }
        if (i < s.size()) ++i;
        return r;
    }
};

string esc(const string& x) {
    string r;
    for (char c : x) {
        if (c == '"' || c == '\\') { r += '\\'; r += c; }
        else if (c == '\n') r += "\\n";
        else r += c;
    }
    return r;
}

// ---------------- records (custom dynamic array) ----------------
struct Rec { long long id; string prn; long long year; string status; double priority; };

DynamicArray<Rec> load(const J& req) {
    DynamicArray<Rec> v;
    const DynamicArray<J>& records = req.at("records").a;
    for (size_t i = 0; i < records.size(); ++i) {
        const J& r = records[i];
        v.push_back({r.at("id").num(), r.at("prn").str(),
                     r.at("graduation_year").num(), r.at("status").str(),
                     r.at("priority").n});
    }
    return v;
}

string ids(const DynamicArray<long long>& v) {
    string r = "[";
    for (size_t i = 0; i < v.size(); ++i) {
        if (i) r += ",";
        r += to_string(v[i]);
    }
    return r + "]";
}

// ---------------- insertion sort ----------------
int statusRank(const string& s) {
    return s == "PENDING" ? 0 : s == "COMPLETED" ? 2 : 1;
}

void sortRecs(DynamicArray<Rec>& a, const string& key) {
    auto before = [&](const Rec& x, const Rec& y) {
        if (key == "graduation_year") return x.year < y.year;
        if (key == "status") return statusRank(x.status) < statusRank(y.status);
        if (key == "priority") return x.priority > y.priority;
        return x.prn < y.prn;
    };
    for (size_t i = 1; i < a.size(); ++i) {
        Rec current = a[i];
        int j = (int)i - 1;
        while (j >= 0 && before(current, a[(size_t)j])) {
            a[(size_t)j + 1] = a[(size_t)j];
            --j;
        }
        a[(size_t)j + 1] = current;
    }
}

// ---------------- doubly linked list ----------------
struct Node { long long id; Node *prev = nullptr, *next = nullptr; };
struct DList {
    Node *head = nullptr, *tail = nullptr;
    int size = 0;

    void push_back(long long id) {
        Node* n = new Node{id};
        if (!tail) head = tail = n;
        else { tail->next = n; n->prev = tail; tail = n; }
        size++;
    }
    bool remove(long long id) {
        for (Node* n = head; n; n = n->next) if (n->id == id) {
            if (n->prev) n->prev->next = n->next; else head = n->next;
            if (n->next) n->next->prev = n->prev; else tail = n->prev;
            delete n; size--; return true;
        }
        return false;
    }
    DynamicArray<long long> forward() const {
        DynamicArray<long long> v;
        for (Node* n = head; n; n = n->next) v.push_back(n->id);
        return v;
    }
    ~DList() {
        while (head) { Node* n = head->next; delete head; head = n; }
    }
};

// ---------------- array-based priority queue ----------------
// Highest priority is removed first. This is an array-based Priority Queue ADT,
// not a binary heap.
struct PQ {
    DynamicArray<Rec> items;
    static bool before(const Rec& a, const Rec& b) {
        return a.priority > b.priority || (a.priority == b.priority && a.id < b.id);
    }
    void push(const Rec& r) { items.push_back(r); }
    Rec pop() {
        size_t best = 0;
        for (size_t i = 1; i < items.size(); ++i)
            if (before(items[i], items[best])) best = i;
        Rec top = items[best];
        items.erase(best);
        return top;
    }
    bool empty() const { return items.empty(); }
};

// ---------------- circular queue ----------------
struct CQ {
    DynamicArray<long long> buf;
    int head = 0, count = 0;
    explicit CQ(int cap) : buf((size_t)cap) {}
    bool full() const { return count == (int)buf.size(); }
    bool empty() const { return count == 0; }
    void enqueue(long long x) { buf[(size_t)((head + count) % (int)buf.size())] = x; count++; }
    long long dequeue() {
        long long x = buf[(size_t)head];
        head = (head + 1) % (int)buf.size();
        count--;
        return x;
    }
};

// ---------------- stack ----------------
struct Stack {
    DynamicArray<long long> a;
    void push(long long x) { a.push_back(x); }
    long long pop() { long long x = a.back(); a.pop_back(); return x; }
    bool empty() const { return a.empty(); }
};

int main() {
    string in((istreambuf_iterator<char>(cin)), istreambuf_iterator<char>());
    P p(in); J req = p.val();
    string cmd = req.at("cmd").str();

    if (cmd == "search") { // exact PRN lookup using binary search
        DynamicArray<Rec> a = load(req);
        sortRecs(a, "prn");
        string q = req.at("prn").str();
        int lo = 0, hi = (int)a.size() - 1;
        while (lo <= hi) {
            int m = (lo + hi) / 2;
            if (a[(size_t)m].prn == q) {
                cout << "{\"found\":true,\"id\":" << a[(size_t)m].id << "}";
                return 0;
            }
            if (a[(size_t)m].prn < q) lo = m + 1;
            else hi = m - 1;
        }
        cout << "{\"found\":false,\"id\":null}";
    } else if (cmd == "sort") {
        DynamicArray<Rec> a = load(req);
        sortRecs(a, req.at("key").str());
        DynamicArray<long long> v;
        for (size_t i = 0; i < a.size(); ++i) v.push_back(a[i].id);
        cout << "{\"ids\":" << ids(v) << "}";
    } else if (cmd == "pending_list") { // doubly linked list of pending alumni
        DList l;
        DynamicArray<Rec> a = load(req);
        for (size_t i = 0; i < a.size(); ++i)
            if (a[i].status == "PENDING") l.push_back(a[i].id);
        const DynamicArray<J>& removals = req.at("remove").a;
        for (size_t i = 0; i < removals.size(); ++i) l.remove(removals[i].num());
        cout << "{\"ids\":" << ids(l.forward()) << ",\"size\":" << l.size << "}";
    } else if (cmd == "schedule") { // priority queue -> circular queue batches
        DynamicArray<Rec> a = load(req);
        int bs = (int)req.at("batch_size").num();
        if (bs < 1) bs = 10;
        PQ pq;
        for (size_t i = 0; i < a.size(); ++i) pq.push(a[i]);
        CQ cq(bs);
        DynamicArray<long long> order;
        string batches = "[";
        bool first = true;
        while (!pq.empty() || !cq.empty()) {
            while (!pq.empty() && !cq.full()) cq.enqueue(pq.pop().id);
            DynamicArray<long long> b;
            while (!cq.empty()) b.push_back(cq.dequeue());
            for (size_t i = 0; i < b.size(); ++i) order.push_back(b[i]);
            batches += (first ? "" : ",") + ids(b);
            first = false;
        }
        cout << "{\"order\":" << ids(order) << ",\"batches\":" << batches << "]}";
    } else if (cmd == "undo") { // actions oldest -> newest; pop the newest
        Stack s;
        const DynamicArray<J>& actions = req.at("actions").a;
        for (size_t i = 0; i < actions.size(); ++i) s.push(actions[i].num());
        if (s.empty()) cout << "{\"action_id\":null,\"remaining\":0}";
        else {
            long long t = s.pop();
            cout << "{\"action_id\":" << t << ",\"remaining\":" << s.a.size() << "}";
        }
    } else {
        cout << "{\"error\":\"unknown command\"}";
        return 1;
    }
    return 0;
}
