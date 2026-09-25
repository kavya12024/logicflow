b = [' ']*9
def win(p):
    for a,c,d in [(0,1,2),(3,4,5),(6,7,8),
                  (0,3,6),(1,4,7),(2,5,8),
                  (0,4,8),(2,4,6)]:
        if b[a] == b[c] == b[d] == p:
            return True
    def mini():
    if win('O'): return 1
    if win('X'): return -1
    if ' ' not in b: return 0
    s = []
    for i in range(9):
        if b[i] == ' ':
            b[i] = 'O'
            s.append(mini())
            b[i] = ' '
    return max(s)
def best():
    score, move = -2, 0
    for i in range(9):
        if b[i] == ' ':
            b[i] = 'O'
            s = mini()
            b[i] = ' '
            if s > score:
                score, move = s, i
    return move
while ' ' in b:
    print(b[:3],"\n" ,b[3:6],"\n", b[6:])
    p = int(input("Your move 1-9: ")) - 1
    b[p] = 'X'
    if win('X')
        print("You win!")
        break
    if ' ' not  b:
        print("Draw!")
        break
    b[best()] = 'O'
    if win('O'):
        print(b[:3], b[3:6], b[6:])
        print("Computer wins!")
        break
