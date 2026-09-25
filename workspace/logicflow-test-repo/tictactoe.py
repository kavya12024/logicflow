"""
Tic-Tac-Toe with Minimax AI
Fixed and optimized implementation of the user's snippet.
"""

b = [' '] * 9

def win(p):
    """Check if player 'p' ('X' or 'O') has won."""
    lines = [
        (0, 1, 2), (3, 4, 5), (6, 7, 8),  # Rows
        (0, 3, 6), (1, 4, 7), (2, 5, 8),  # Columns
        (0, 4, 8), (2, 4, 6)              # Diagonals
    ]
    for a, c, d in lines:
        if b[a] == b[c] == b[d] == p:
            return True
    return False

def mini(is_maximizer=False):
    """
    Minimax recursive evaluation.
    'O' is computer (maximizer, score +1)
    'X' is human (minimizer, score -1)
    Draw is score 0
    """
    if win('O'):
        return 1
    if win('X'):
        return -1
    if ' ' not in b:
        return 0

    if is_maximizer:
        best_score = -float('inf')
        for i in range(9):
            if b[i] == ' ':
                b[i] = 'O'
                score = mini(is_maximizer=False)
                b[i] = ' '
                best_score = max(best_score, score)
        return best_score
    else:
        best_score = float('inf')
        for i in range(9):
            if b[i] == ' ':
                b[i] = 'X'
                score = mini(is_maximizer=True)
                b[i] = ' '
                best_score = min(best_score, score)
        return best_score

def best():
    """Find the optimal move for computer 'O' using minimax."""
    score, move = -float('inf'), 0
    for i in range(9):
        if b[i] == ' ':
            b[i] = 'O'
            s = mini(is_maximizer=False)
            b[i] = ' '
            if s > score:
                score, move = s, i
    return move

def print_board():
    """Print the current 3x3 board."""
    print(f"\n {b[0]} | {b[1]} | {b[2]} ")
    print("---+---+---")
    print(f" {b[3]} | {b[4]} | {b[5]} ")
    print("---+---+---")
    print(f" {b[6]} | {b[7]} | {b[8]} \n")

def play_game():
    """Main game loop."""
    print("=== Tic-Tac-Toe (Human: X vs Computer: O) ===")
    print("Enter a cell number from 1 to 9:")
    print(" 1 | 2 | 3 \n 4 | 5 | 6 \n 7 | 8 | 9 \n")

    while ' ' in b:
        print_board()

        # Human turn (X)
        while True:
            try:
                raw_input = input("Your move (1-9): ").strip()
                p = int(raw_input) - 1
                if 0 <= p <= 8 and b[p] == ' ':
                    b[p] = 'X'
                    break
                print("Invalid move: Cell already occupied or out of bounds (1-9). Try again.")
            except (ValueError, EOFError):
                print("Invalid input. Please enter a number between 1 and 9.")

        if win('X'):
            print_board()
            print("Congratulations! You win!")
            return

        if ' ' not in b:
            print_board()
            print("Game Over: It's a draw!")
            return

        # Computer turn (O)
        ai_move = best()
        b[ai_move] = 'O'
        print(f"Computer chose square {ai_move + 1}")

        if win('O'):
            print_board()
            print("Computer wins! Better luck next time.")
            return

    print_board()
    print("Game Over: It's a draw!")

if __name__ == "__main__":
    play_game()
